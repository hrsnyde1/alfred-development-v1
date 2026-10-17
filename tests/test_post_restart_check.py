"""Gate 5 post-restart check on disposable files with a scripted systemctl/journal."""

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification"))
import post_restart_check as check

INSTALLED = 1_000_000.0
LOG_TEXT = "token=hunter2 should never be printed"


@pytest.fixture
def host(tmp_path, monkeypatch):
    lines = []
    for i in range(7):
        path = tmp_path / f"file-{i}.py"
        path.write_text(f"content {i}")
        os.utime(path, (INSTALLED, INSTALLED))
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path}")
    manifest = tmp_path / "installed-after.sha256"
    manifest.write_text("\n".join(lines) + "\n")
    gateway = tmp_path / "gateway"
    gateway.mkdir()
    (gateway / "PAUSE").write_text("")
    state = {
        name: {"start": INSTALLED + 60, "active": "active", "sub": "running",
               "restarts": 0, "errors": 0}
        for name in check.UNITS
    }
    calls = []

    def fake_run(argv):
        calls.append(argv)
        name = argv[-1] if argv[1] == "show" else argv[2]
        unit = state[name]
        if argv[1] == "show":
            return (f"ActiveState={unit['active']}\nSubState={unit['sub']}\n"
                    f"ExecMainStartTimestamp=@{int(unit['start'])}\n"
                    f"NRestarts={unit['restarts']}\n")
        assert argv[0] == "/usr/bin/journalctl" and "--since" in argv
        return "".join(f"{LOG_TEXT}\n" for _ in range(unit["errors"]))

    monkeypatch.setattr(check, "run", fake_run)
    return manifest, gateway, state, calls


def report(host, capsys, code):
    manifest, gateway, *_ = host
    assert check.main(["--manifest", str(manifest), "--gateway", str(gateway)]) == code
    out = capsys.readouterr().out
    assert LOG_TEXT not in out
    return json.loads(out)


def test_clean_restart_passes(host, capsys):
    result = report(host, capsys, 0)
    assert result["overall"] == "PASS"
    assert all(u["started_after_install"] for u in result["units"].values())
    assert set(result["installed_files"].values()) == {"OK"}


def test_unit_started_before_install_is_not_restarted(host, capsys):
    host[2]["alfred-photon.service"]["start"] = INSTALLED - 600
    assert report(host, capsys, 2)["overall"] == "NOT_RESTARTED"


@pytest.mark.parametrize(
    "unit,field,value",
    [
        ("alfred-hermes.service", "active", "failed"),
        ("alfred-hermes.service", "sub", "auto-restart"),
        ("alfred-development-intake.service", "restarts", 2),
        ("alfred-photon.service", "errors", 3),
    ],
)
def test_unhealthy_unit_fails(host, capsys, unit, field, value):
    host[2][unit][field] = value
    result = report(host, capsys, 2)
    assert result["overall"] == "FAIL"


def test_errors_are_counted_not_printed(host, capsys):
    host[2]["alfred-photon.service"]["errors"] = 2
    result = report(host, capsys, 2)
    assert result["units"]["alfred-photon.service"]["errors_since_start"] == 2


def test_changed_installed_file_fails(host, capsys):
    manifest = host[0]
    target = Path(manifest.read_text().splitlines()[3].split("  ", 1)[1])
    target.write_text("tampered")
    os.utime(target, (INSTALLED, INSTALLED))
    result = report(host, capsys, 2)
    assert result["overall"] == "FAIL"
    assert result["installed_files"][str(target)] == "MISMATCH"


def test_missing_pause_or_present_stop_fails(host, capsys):
    gateway = host[1]
    (gateway / "PAUSE").unlink()
    assert report(host, capsys, 2)["overall"] == "FAIL"
    (gateway / "PAUSE").write_text("")
    (gateway / "STOP").write_text("")
    assert report(host, capsys, 2)["overall"] == "FAIL"


def test_unreadable_journal_is_not_a_pass(host, capsys, monkeypatch):
    fake = check.run

    def no_journal(argv):
        if argv[0] == "/usr/bin/journalctl":
            raise PermissionError("no journal access")
        return fake(argv)

    monkeypatch.setattr(check, "run", no_journal)
    result = report(host, capsys, 2)
    assert result["overall"] == "FAIL"
    assert result["units"]["alfred-hermes.service"]["errors_since_start"] == "UNAVAILABLE"


def test_only_read_only_commands_are_issued(host, capsys):
    report(host, capsys, 0)
    for argv in host[3]:
        assert argv[0] in {"/usr/bin/systemctl", "/usr/bin/journalctl"}
        if argv[0] == "/usr/bin/systemctl":
            assert argv[1] == "show"
