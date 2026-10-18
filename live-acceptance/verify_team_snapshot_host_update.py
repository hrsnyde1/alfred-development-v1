"""Read-only post-install check for the team-snapshot update (PR #25).

Run as alfred while the activation marker is absent. The only files written are a
synthetic snapshot in a private /tmp directory that is removed before exit. No
model, worker, Photon or Gateway call; services are only queried.

Prints one PASS line and exits 0, or FAIL with the first failed check and exits 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEVELOPER_ROOT = Path("/opt/alfred-developer-v1")
FRESH_ROOT = Path("/usr/local/lib/alfred-fresh-v1")
TEAM_ROOT = Path("/var/lib/alfred-development-state/team")
CTO = Path("/home/alfred/Git/alfred/.dev/bin/cto.py")
MANIFEST_SHA256 = "dabaeae44a69116ab4c9048e93554e53567decc17ff6d60e5b2fc320c3dcbc77"
GATEWAY_UNITS = ("alfred-development-gateway.service", "alfred-development-gateway.timer")
ACTIVE_UNITS = ("alfred-development-intake.service", "alfred-photon.service",
                "alfred-hermes.service")
NEW = ("builder", "qa", "code_reviewer")
EXISTING = ("frontend", "backend", "full_stack", "devops", "data_engineer", "data_scientist",
            "ai_ml", "integration", "security", "mobile", "performance")


class AcceptanceFailed(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailed(message)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_release(root: Path, manifest_sha256: str) -> None:
    manifest = root / "developer_v1" / "release.sha256"
    require(sha256(manifest) == manifest_sha256, "installed release manifest digest")
    listed = set()
    for line in manifest.read_text().splitlines():
        digest, _, relative = line.partition("  ")
        target = root / relative
        require(relative.startswith("developer_v1/") and ".." not in Path(relative).parts,
                "release manifest entry")
        require(target.is_file() and not target.is_symlink(), "missing installed file " + relative)
        require(sha256(target) == digest, "installed file digest " + relative)
        listed.add(relative)
    present = {str(p.relative_to(root)) for p in (root / "developer_v1").rglob("*")
               if p.is_file() and "__pycache__" not in p.parts}
    require(present - listed == {"developer_v1/release.sha256"}, "unlisted installed files")
    require("developer_v1/team_snapshot.py" in listed, "team_snapshot.py not released")


def check_imports(root: Path, fresh: Path):
    from developer_v1 import agent_profiles, pipeline, router, team_snapshot
    from fresh_v1 import host
    for module in (agent_profiles, pipeline, router, team_snapshot):
        require(Path(module.__file__).resolve().is_relative_to((root / "developer_v1").resolve()),
                "imported developer_v1 is not the installed one")
    require(Path(host.__file__).resolve().is_relative_to((fresh / "fresh_v1").resolve()),
            "imported fresh_v1 is not the installed one")
    return agent_profiles, pipeline, router, team_snapshot, host


def check_specialists(router, host) -> None:
    require(set(router.SPECIALISTS) == set(EXISTING) | set(NEW), "specialists.json roster")
    for role in NEW:
        require(router.CAPABILITY_BY_ROLE.get(role) == {"code"}, "capabilities for " + role)
        require(role in host.SUPPORTED_SPECIALISTS, "fresh_v1 cannot staff " + role)
    evidence = {"repository_evidence": {"files": ["a.py"]}}
    spec = {"title": "", "sections": {"objective": "Fix the retry bug in the Alfred gateway"}}
    require(router.select_specialists(spec, evidence) == ["builder"], "CTO routing to builder")
    spec["sections"]["objective"] = "Fix the backend API endpoint error"
    require(router.select_specialists(spec, evidence) == ["backend"],
            "existing CTO routing changed")


def check_builtin(agent_profiles, pipeline, team_snapshot, team_root: Path, private: Path) -> None:
    require(not team_root.exists() and not team_root.is_symlink(),
            "host team snapshot directory already exists")
    require(team_snapshot.ROOT == TEAM_ROOT, "default snapshot root changed")
    for role in (*EXISTING, *NEW):
        builtin = agent_profiles.identity(pipeline.BUILTIN_PROFILE.get(role, role))
        for root in (team_root, private / "absent"):
            text, record = team_snapshot.profile(role, builtin, root=root)
            require(text == builtin and record == team_snapshot.BUILTIN,
                    "prompt without snapshot differs from builtin: " + role)


def write_snapshot(root: Path, agent: str) -> str:
    folder = root / agent
    folder.mkdir(mode=0o700, parents=True)
    files = {"Soul.md": "Synthetic soul marker.\n", "Role.md": "Synthetic role marker.\n",
             "Tools.md": "Synthetic tools marker: you may use the shell.\n"}
    for name, text in files.items():
        (folder / name).write_text(text)
    manifest = {"schema": "alfred.team-snapshot/1", "agent": agent,
                "approvedAt": "2026-10-18T00:00:00Z", "approvedBy": "passkey",
                "settings": {"model_id": None, "effort": "Medium", "style": "Deliberate"},
                "files": {n: hashlib.sha256(t.encode()).hexdigest() for n, t in files.items()}}
    raw = json.dumps(manifest).encode()
    (folder / "manifest.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def check_synthetic(agent_profiles, team_snapshot, private: Path) -> None:
    root = private / "team"
    digest = write_snapshot(root, "backend")
    builtin = agent_profiles.identity("backend")
    text, record = team_snapshot.profile("backend", builtin, root=root)
    require(record == digest, "synthetic snapshot was not used")
    order = [builtin.strip(), team_snapshot.STYLE_LINES["Deliberate"], "Synthetic soul marker",
             "Synthetic role marker", "Synthetic tools marker", team_snapshot.SAFETY]
    positions = [text.find(marker) for marker in order]
    require(-1 not in positions and positions == sorted(positions), "composition order")
    require(text.endswith(team_snapshot.SAFETY), "safety rules are not last")
    require(team_snapshot.load("cto", root) is None, "cto read another agent's snapshot")
    digest = write_snapshot(root, "cto")
    require(team_snapshot.load("cto", root).manifest_sha256 == digest, "cto snapshot")

    (root / "backend" / "Soul.md").write_text("Changed after approval.\n")
    require(team_snapshot.profile("backend", builtin, root=root) == (builtin, "builtin"),
            "tampered snapshot did not fall back")
    os.remove(root / "backend" / "Soul.md")
    os.symlink(root / "cto" / "Soul.md", root / "backend" / "Soul.md")
    require(team_snapshot.profile("backend", builtin, root=root) == (builtin, "builtin"),
            "symlinked snapshot file did not fall back")


def check_plan_schema(fresh: Path) -> None:
    schema = json.loads((fresh / "v1_cto" / "plan.schema.json").read_text())
    require(schema["properties"].get("team_profile", {}).get("pattern") == "^[0-9a-f]{64}$",
            "installed plan schema lacks team_profile")


def unit_state(systemctl: str) -> str:
    result = subprocess.run([systemctl, "show", "-p", "ActiveState", "-p", "Result",
                             *GATEWAY_UNITS], capture_output=True, check=True, timeout=15)
    return hashlib.sha256(result.stdout).hexdigest()


def check_host_state(args) -> None:
    require(not (args.developer_root / "active").exists(), "activation marker present")
    require(sha256(args.cto) == args.cto_sha256, "CTO source changed")
    require(sha256(args.fresh_root / "v1_cto" / "cto.py") == args.installed_cto_sha256,
            "installed v1_cto/cto.py changed")
    require(unit_state(args.systemctl) == args.gateway_sha256, "Gateway unit state changed")
    for unit in ACTIVE_UNITS:
        state = subprocess.run([args.systemctl, "is-active", unit], capture_output=True,
                               text=True, timeout=15).stdout.strip()
        require(state == "active", unit + " is not active")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cto-sha256", required=True)
    parser.add_argument("--installed-cto-sha256", required=True)
    parser.add_argument("--gateway-sha256", required=True)
    parser.add_argument("--developer-root", type=Path, default=DEVELOPER_ROOT)
    parser.add_argument("--fresh-root", type=Path, default=FRESH_ROOT)
    parser.add_argument("--team-root", type=Path, default=TEAM_ROOT)
    parser.add_argument("--cto", type=Path, default=CTO)
    parser.add_argument("--manifest-sha256", default=MANIFEST_SHA256)
    parser.add_argument("--systemctl", default="/usr/bin/systemctl")
    args = parser.parse_args(argv)
    # Warnings from the deliberately broken synthetic snapshots are expected.
    logging.getLogger("developer_v1.team_snapshot").setLevel(logging.ERROR)
    private = Path(tempfile.mkdtemp(prefix="alfred-team-snapshot-check-", dir="/tmp"))
    try:
        check_release(args.developer_root, args.manifest_sha256)
        agent_profiles, pipeline, router, team_snapshot, host = check_imports(
            args.developer_root, args.fresh_root)
        check_specialists(router, host)
        check_builtin(agent_profiles, pipeline, team_snapshot, args.team_root, private)
        check_synthetic(agent_profiles, team_snapshot, private)
        check_plan_schema(args.fresh_root)
        check_host_state(args)
    except Exception as exc:  # noqa: BLE001 - every failure is one FAIL line
        print(f"FAIL: {exc}" if isinstance(exc, AcceptanceFailed)
              else f"FAIL: {type(exc).__name__}")
        return 1
    finally:
        shutil.rmtree(private, ignore_errors=True)
    print("PASS: team snapshot update verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
