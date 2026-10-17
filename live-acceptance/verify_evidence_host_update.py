"""Read-only post-install check; run as alfred while activation is disabled.

Only a staging-environment synthetic grant is written, in a private /tmp
directory that is removed before this process exits. No Photon or worker call.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import os
import pwd
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from developer_v1.gateway_adapter import read_gateway_inputs
from developer_v1.owner_grants import (
    DevelopmentGrantIssuer, ProtectedDevelopmentAuthority, _read,
)
from developer_v1.router import Denied, canonical_binding

PROJECT = "dev-v1-accept"
TASK = "T-0002"
GRANTS = Path("/var/lib/alfred-development-grants")
INTAKE = Path("/usr/local/lib/alfred-v1.1/trusted_intake.py")
CTO = Path("/home/alfred/Git/alfred/.dev/bin/cto.py")
GATEWAY_UNITS = ("alfred-development-gateway.service", "alfred-development-gateway.timer")
ACTIVE_UNITS = ("alfred-development-intake.service", "alfred-photon.service", "alfred-hermes.service")


class AcceptanceFailed(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailed(message)


def import_installed_intake(source: Path = INTAKE) -> None:
    """Import the actual installed entry point without invoking main()."""
    try:
        spec = importlib.util.spec_from_file_location("_alfred_intake_update_check", source)
        _require(spec is not None and spec.loader is not None, "Intake import unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _require(module.DevelopmentGrantIssuer is DevelopmentGrantIssuer,
                 "Intake did not import updated grant issuer")
        _require(hasattr(module.IntakeGate, "dispatch"), "Intake dispatch unavailable")
    except AcceptanceFailed:
        raise
    except Exception as exc:
        raise AcceptanceFailed("installed trusted Intake import failed") from exc


def historical_rejected(root: Path, expected: dict, marker: Path,
                        *, environment: str = "host") -> None:
    """Reach the missing-evidence check even if the old grant has expired."""
    matches = []
    for path in root.glob("grant-*.json"):
        grant = _read(root, path.name)
        if grant.get("project") == expected["project"] and grant.get("task_id") == expected["task_id"]:
            matches.append((path.stem.removeprefix("grant-"), grant))
    _require(len(matches) == 1, "historical task grant is not unique")
    reference, grant = matches[0]
    _require(all(grant.get(key) == value for key, value in expected.items()),
             "historical grant binding differs from canonical task")
    _require(grant.get("environment") == environment, "historical grant environment differs")
    _require(all(not (root / f"{kind}-{reference}.json").exists()
                 for kind in ("challenge", "decision", "issuance")),
             "historical approval evidence unexpectedly exists")
    _require(isinstance(grant.get("expires_at"), (int, float)),
             "historical grant expiry unavailable")
    # The real activation marker is deliberately absent during this check.
    # A root-owned, mode-0644 installed source is a read-only diagnostic marker.
    authority = ProtectedDevelopmentAuthority(root,
        clock=lambda: min(time.time(), grant["expires_at"] - 1), environment=environment)
    if environment == "host":
        authority.activation_marker = marker
    try:
        authority.verify(reference, expected)
    except Denied as exc:
        _require(str(exc) == "development grant lacks trusted approval evidence",
                 "historical grant rejected for a different reason")
    else:
        raise AcceptanceFailed("historical grant unexpectedly verified")


def synthetic_evidence() -> None:
    with tempfile.TemporaryDirectory(prefix="alfred-evidence-check-", dir="/tmp") as temporary:
        root = Path(temporary)
        _require(root.resolve() != GRANTS.resolve(), "fixture grant root is production")
        request = {
            "schema": "alfred.development-approval-request/1",
            "project": "fixture-only", "task_id": "T-0099",
            "spec_sha256": "a" * 64, "plan_sha256": "b" * 64,
            "repository": str(root / "repo"), "worktree_root": str(root / "worktrees"),
            "scope": ["calculator.py"], "specialists": ["backend"],
            "state": "pending_owner_decision",
        }
        issuer = DevelopmentGrantIssuer(root, owner_sender_id="fixture-owner",
            preview_sender=lambda _space, _text: "fixture-outbound-id",
            sidecar_uid=4242, environment="staging")
        issuer.stage(request, space_id="fixture-dm", peer_uid=0)
        phrase = f"Approve development fixture-only T-0099 {request['plan_sha256'][:12]}"
        decision = issuer.observe({
            "messageId": "fixture-inbound-id", "direction": "inbound",
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "sender": {"id": "fixture-owner"},
            "space": {"id": "fixture-dm", "type": "dm"},
            "nativeReplyTargetGuid": "fixture-outbound-id", "nativeIsForward": False,
            "content": {"type": "text", "text": phrase},
        }, peer_uid=4242)
        expected = {key: value for key, value in request.items() if key != "state"}
        expected["schema"] = "alfred.development-grant/1"
        grant = ProtectedDevelopmentAuthority(root, environment="staging").verify(
            decision["reference"], expected)
        _require(grant["environment"] == "staging", "synthetic grant escaped staging")


def services_and_code_unchanged(cto_sha256: str, gateway_sha256: str) -> None:
    _require(hashlib.sha256(CTO.read_bytes()).hexdigest() == cto_sha256,
             "CTO code changed")
    for unit in ACTIVE_UNITS:
        result = subprocess.run(["systemctl", "is-active", "--quiet", unit], check=False)
        _require(result.returncode == 0, "required service inactive")
    gateway = subprocess.check_output([
        "systemctl", "show", "-p", "ActiveState", "-p", "Result", *GATEWAY_UNITS])
    _require(hashlib.sha256(gateway).hexdigest() == gateway_sha256,
             "Gateway state changed")
    _require(gateway.count(b"Result=success") == len(GATEWAY_UNITS),
             "Gateway result is not successful")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cto-sha256", required=True)
    parser.add_argument("--gateway-sha256", required=True)
    args = parser.parse_args()
    try:
        _require(os.geteuid() == pwd.getpwnam("alfred").pw_uid,
                 "acceptance must run as the Intake identity")
        _require(not Path("/opt/alfred-developer-v1/active").exists(),
                 "development activation marker is present")
        import_installed_intake()
        inputs = read_gateway_inputs(gateway_root=Path("/home/alfred/Git/alfred"),
            gateway_state=Path("/home/alfred/Alfred/gateway"),
            registry_path=Path("/home/alfred/Git/alfred/registry/projects.yaml"),
            project_id=PROJECT, task_id=TASK)
        candidates = [(_read(GRANTS, path.name), path.stem.removeprefix("grant-"))
                      for path in GRANTS.glob("grant-*.json")]
        old = [grant for grant, _ in candidates
               if grant.get("project") == PROJECT and grant.get("task_id") == TASK]
        _require(len(old) == 1, "historical task grant is not unique")
        grant = old[0]
        _, _, expected = canonical_binding(inputs.spec_raw, inputs.plan_raw,
            project=PROJECT, task_id=TASK, repository=inputs.repository,
            worktree_root=Path(grant["worktree_root"]), scope=grant["scope"],
            specialists=grant["specialists"], spec_decoder=inputs.spec_decoder)
        historical_rejected(GRANTS, expected, INTAKE)
        synthetic_evidence()
        services_and_code_unchanged(args.cto_sha256, args.gateway_sha256)
    except Exception as exc:
        if isinstance(exc, AcceptanceFailed):
            print(f"FAIL — {exc}", file=sys.stderr)
        else:
            print("FAIL — post-install acceptance unavailable", file=sys.stderr)
        raise SystemExit(1) from None
    print("PASS — Intake import, historical rejection, isolated synthetic evidence, services, Gateway and CTO")


if __name__ == "__main__":
    main()
