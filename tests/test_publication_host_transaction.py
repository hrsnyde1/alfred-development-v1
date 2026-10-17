"""Execute the reviewed host transaction against disposable paths only."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "publication_host_transaction.sh"
PACKAGE = ROOT / "developer_v1"


def test_operator_procedure_is_pinned_and_cannot_stage_publication():
    source = SCRIPT.read_text()
    procedure = (ROOT / "PUBLICATION_APPROVAL_HOST.md").read_text()
    assert sha(SCRIPT) in procedure
    assert source.count('"$SYSTEMCTL" restart alfred-development-intake.service') == 2
    assert "stage_publication_approval" not in source
    assert "prepare_publication_authorization" not in source
    assert "--stage" not in source and "--prepare" not in source


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp: Path) -> tuple[Path, Path, Path, Path, dict[Path, bytes]]:
    stage = tmp / "stage"
    shutil.copytree(PACKAGE, stage / "developer_v1",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    host = tmp / "host"
    host.mkdir()
    installed = host / "developer_v1"
    shutil.copytree(stage / "developer_v1", installed)
    changed = installed / "owner_grants.py"
    changed.write_bytes(changed.read_bytes() + b"\n# prior reviewed fixture\n")
    manifest = installed / "release.sha256"
    rows = manifest.read_text().splitlines()
    rows = [f"{sha(changed)}  developer_v1/owner_grants.py"
            if row.endswith("  developer_v1/owner_grants.py") else row for row in rows]
    manifest.write_text("\n".join(rows) + "\n")
    intake = tmp / "trusted_intake.py"
    intake.write_bytes((stage / "developer_v1/trusted_intake_development.py").read_bytes()
                       + b"\n# prior reviewed fixture\n")
    active = host / "active"
    active.write_text("enabled\n")
    active.chmod(0o644)
    plan = tmp / "state/dev-v1-accept/T-0002/publication-plan.json"
    plan.parent.mkdir(parents=True)
    plan.write_text('{"fixture":"exact-plan"}\n')
    grant = tmp / "grants/grant-existing.json"
    qa = tmp / "qa/qa-report.json"
    reviewer = tmp / "reviewer/publication-handoff.json"
    for path, content in ((grant, b"existing development grant\n"),
                          (qa, b"existing QA evidence\n"),
                          (reviewer, b"existing Reviewer approval\n")):
        path.parent.mkdir(parents=True)
        path.write_bytes(content)
    evidence = {path: path.read_bytes() for path in (grant, qa, reviewer, plan)}
    systemctl = tmp / "systemctl-fixture"
    systemctl.write_text("#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$FIXTURE_SERVICE_LOG\"\n"
        "case \"$1\" in\n"
        "  is-active) exit 0 ;;\n"
        "  show) printf 'ActiveState=active\\nResult=success\\n'; exit 0 ;;\n"
        "  restart) test \"${FIXTURE_FAIL_RESTART:-0}\" != 1; exit $? ;;\n"
        "esac\nexit 1\n")
    systemctl.chmod(0o755)
    source = SCRIPT.read_text()
    source = source.replace("if [[ $EUID -ne 0 ]]; then", "if false; then", 1)
    values = {
        "STAGE": stage, "ROOT": host, "INTAKE": intake,
        "PLAN": plan, "AUTH": tmp / "authorizations/T-0002.json",
        "SYSTEMCTL": systemctl,
        "OLD_RELEASE": sha(manifest), "OLD_INTAKE": sha(intake),
        "NEW_RELEASE": sha(stage / "developer_v1/release.sha256"),
        "NEW_INTAKE": sha(stage / "developer_v1/trusted_intake_development.py"),
        "PLAN_SHA": sha(plan),
    }
    for name, value in values.items():
        source, count = re.subn(rf"^{name}=.*$", f"{name}={value}", source,
                                count=1, flags=re.MULTILINE)
        assert count == 1, name
    source = source.replace("0:644", f"{os.geteuid()}:644")
    runner = tmp / "transaction-fixture.sh"
    runner.write_text(source)
    runner.chmod(0o700)
    return runner, host, intake, tmp / "systemctl.log", evidence


def run(script: Path, action: str, log: Path, *, fail_restart: bool = False) -> subprocess.CompletedProcess:
    env = {**os.environ, "FIXTURE_SERVICE_LOG": str(log),
           "FIXTURE_FAIL_RESTART": "1" if fail_restart else "0"}
    return subprocess.run(["/bin/bash", str(script), action], capture_output=True,
                          text=True, env=env, timeout=20)


def assert_preserved(evidence: dict[Path, bytes]) -> None:
    for path, content in evidence.items():
        assert path.read_bytes() == content


def test_install_then_manual_rollback_preserves_evidence_and_marker():
    with tempfile.TemporaryDirectory(prefix="publication-host-transaction-") as temporary:
        script, host, intake, log, evidence = fixture(Path(temporary))
        prior_release = sha(host / "developer_v1/release.sha256")
        prior_intake = sha(intake)
        installed = run(script, "install", log)
        assert installed.returncode == 0, installed.stderr
        assert (host / "active").is_file()
        assert sha(host / "developer_v1/release.sha256") == sha(PACKAGE / "release.sha256")
        assert sha(intake) == sha(PACKAGE / "trusted_intake_development.py")
        assert_preserved(evidence)
        rolled = run(script, "rollback", log)
        assert rolled.returncode == 0, rolled.stderr
        assert (host / "active").is_file()
        assert sha(host / "developer_v1/release.sha256") == prior_release
        assert sha(intake) == prior_intake
        assert_preserved(evidence)
        restarts = [row for row in log.read_text().splitlines() if row.startswith("restart ")]
        assert restarts == ["restart alfred-development-intake.service"] * 2


def test_partial_install_failure_automatically_restores_marker_and_evidence():
    with tempfile.TemporaryDirectory(prefix="publication-host-failure-") as temporary:
        script, host, intake, log, evidence = fixture(Path(temporary))
        prior_release = sha(host / "developer_v1/release.sha256")
        prior_intake = sha(intake)
        source = script.read_text()
        anchor = '  /usr/bin/mv -T "$PACKAGE/$name.next" "$PACKAGE/$name"\n'
        assert source.count(anchor) == 1
        script.write_text(source.replace(anchor, anchor +
                           '  [[ $name != owner_grants.py ]] || /usr/bin/false\n'))
        result = run(script, "install", log)
        assert result.returncode != 0
        assert "ROLLED_BACK" in result.stderr
        assert (host / "active").is_file()
        assert sha(host / "developer_v1/release.sha256") == prior_release
        assert sha(intake) == prior_intake
        assert_preserved(evidence)
        assert [row for row in log.read_text().splitlines() if row.startswith("restart ")] == [
            "restart alfred-development-intake.service"]


def test_failed_recovery_is_explicit_and_retryable():
    with tempfile.TemporaryDirectory(prefix="publication-host-retry-") as temporary:
        script, host, intake, log, evidence = fixture(Path(temporary))
        source = script.read_text()
        anchor = '  /usr/bin/mv -T "$PACKAGE/$name.next" "$PACKAGE/$name"\n'
        script.write_text(source.replace(anchor, anchor +
                           '  [[ $name != owner_grants.py ]] || /usr/bin/false\n'))
        result = run(script, "install", log, fail_restart=True)
        assert result.returncode != 0
        assert "BLOCKED" in result.stderr
        assert not (host / "active").exists()
        assert (host / "publication-approval-backup-v1/active").is_file()
        assert_preserved(evidence)
        recovered = run(script, "rollback", log)
        assert recovered.returncode == 0, recovered.stderr
        assert (host / "active").is_file()
        assert sha(intake) != sha(PACKAGE / "trusted_intake_development.py")
        assert_preserved(evidence)
