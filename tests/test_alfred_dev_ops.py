"""The restricted root operations helper, against disposable /tmp roots only."""

import hashlib
import io
import json
import tarfile

import pytest

from ops import alfred_dev_ops as ops

NAME = "alfred-fresh-v1-1.0.1-development-handoff.9"
STUB_INSTALLER = b"""import sys, pathlib
args = sys.argv[1:]
if args[0] == "install":
    backup = pathlib.Path(args[args.index("--backup") + 1])
    backup.mkdir()
    (backup / "installed").write_text("yes")
print('{"ok": true}')
"""


def tar_bytes(files):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(NAME + "/" + name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@pytest.fixture
def host(tmp_path, monkeypatch):
    lab, work = tmp_path / "lab", tmp_path / "root"
    (lab / "dist").mkdir(parents=True)
    (lab / "development_handoff9").mkdir()
    work.mkdir()
    pause = tmp_path / "PAUSE"
    pause.touch()
    installer = STUB_INSTALLER
    after = b""  # an empty checksum list verifies trivially in the fixture
    raw = tar_bytes({"development_handoff9/install_patch.py": installer,
                     "development_handoff9/installed-after.sha256": after})
    (lab / "dist" / (NAME + ".tar.gz")).write_bytes(raw)
    pins = {"schema": "alfred.development-release/1", "name": NAME,
            "archive_sha256": hashlib.sha256(raw).hexdigest(),
            "manifest_sha256": "a" * 64,
            "installer": "development_handoff9/install_patch.py",
            "installer_sha256": hashlib.sha256(installer).hexdigest(),
            "installed_after": "development_handoff9/installed-after.sha256",
            "preflight": None, "restart": []}
    (lab / "development_handoff9" / "release.json").write_text(json.dumps(pins))
    for name, value in {"LAB": lab, "WORK": work, "PAUSE": pause,
                        "AUDIT": tmp_path / "audit.jsonl", "PYTHON": "python3"}.items():
        monkeypatch.setattr(ops, name, value)
    calls = []
    real_run = ops.run

    def recording_run(argv, **kwargs):
        calls.append(argv[0] if argv[0] != "python3" else argv[4])
        if argv[0] == "sha256sum":  # empty list: nothing to check in the fixture
            return None
        return real_run(argv, **kwargs)

    monkeypatch.setattr(ops, "run", recording_run)
    return pins, work, pause, calls


def test_install_runs_the_fixed_sequence_from_the_verified_release(host):
    pins, work, pause, calls = host
    result = ops.install(9, pins["archive_sha256"][:12])
    assert result["pause"] == "still set"
    assert calls == ["tar", "verify", "install", "sha256sum"]
    assert (work / (NAME + "-backup") / "installed").read_text() == "yes"


def test_wrong_or_short_confirmation_changes_nothing(host):
    pins, work, _, calls = host
    for answer in ("0" * 12, pins["archive_sha256"][:11], ""):
        with pytest.raises(ops.Refused, match="not confirmed"):
            ops.install(9, answer)
    assert calls == [] and list(work.iterdir()) == []


def test_install_requires_pause(host):
    pins, work, pause, calls = host
    pause.unlink()
    with pytest.raises(ops.Refused, match="PAUSE"):
        ops.install(9, pins["archive_sha256"][:12])
    assert calls == [] and list(work.iterdir()) == []


def test_tampered_archive_or_installer_is_refused(host):
    pins, work, _, calls = host
    archive = ops.LAB / "dist" / (NAME + ".tar.gz")
    good = archive.read_bytes()
    archive.write_bytes(good + b"x")
    with pytest.raises(ops.Refused, match="archive differs"):
        ops.install(9, pins["archive_sha256"][:12])
    assert calls == []
    for path in work.iterdir():
        path.unlink()
    archive.write_bytes(tar_bytes({"development_handoff9/install_patch.py": b"evil",
                                   "development_handoff9/installed-after.sha256": b""}))
    pins_path = ops.LAB / "development_handoff9" / "release.json"
    pins_path.write_text(json.dumps({**pins, "archive_sha256":
                                     hashlib.sha256(archive.read_bytes()).hexdigest()}))
    with pytest.raises(ops.Refused, match="installer differs"):
        ops.install(9, hashlib.sha256(archive.read_bytes()).hexdigest()[:12])
    assert calls == ["tar"]


def test_a_release_cannot_be_installed_twice(host):
    pins, _, _, _ = host
    ops.install(9, pins["archive_sha256"][:12])
    with pytest.raises(ops.Refused, match="already used"):
        ops.install(9, pins["archive_sha256"][:12])


@pytest.mark.parametrize("change", [
    {"restart": ["ssh.service"]},
    {"restart": ["alfred-hermes.service"]},
    {"preflight": "../../tmp/anything.py"},
    {"installer": "development_handoff9/../../evil.py"},
    {"name": "something-else"},
    {"archive_sha256": "short"},
    {"extra": "field"},
])
def test_pins_outside_the_fixed_contract_are_refused(host, change):
    pins, _, _, calls = host
    (ops.LAB / "development_handoff9" / "release.json").write_text(json.dumps({**pins, **change}))
    with pytest.raises(ops.Refused, match="pins invalid"):
        ops.release_pins(9)
    assert calls == []


def test_handoff8_pins_satisfy_the_contract():
    pins = json.loads((ops.Path(__file__).resolve().parents[1] /
                       "development_handoff8" / "release.json").read_text())
    assert pins["restart"] == ["alfred-development-intake.service"]
    assert pins["installer"] == "development_handoff8/install_patch.py"
