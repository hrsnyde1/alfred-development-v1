"""handoff.5: role identities observe PAUSE/STOP through the sandbox's read-only
gateway view and still fail closed whenever the state cannot be observed."""

from pathlib import Path

import pytest

from fresh_v1 import role
from fresh_v1.diagnostics import WorkerFailure

LAB = Path(__file__).resolve().parents[1]


@pytest.fixture
def policy(tmp_path, monkeypatch):
    gateway = tmp_path / "home/alfred/Alfred/gateway"
    gateway.mkdir(parents=True)
    value = {
        "schema": "alfred.fresh-v1-policy/1",
        "enabled": True,
        "gateway_state": str(gateway),
        "jobs": str(tmp_path / "jobs"),
        "project": "dev-v1-accept",
    }
    monkeypatch.setattr(role, "protected_json", lambda path: _read(path, value))
    monkeypatch.setattr(role, "GATEWAY_VIEW", tmp_path / "run/alfred-fresh-v1-gateway")
    return value, gateway, tmp_path


def _read(path, value):
    if path.name == "policy.json":
        return value, "0" * 64
    raise FileNotFoundError(path)  # Past the pause check: the job read is reached.


def run(tmp_path):
    role.main(["qa", "--job", str(tmp_path / "jobs/dev-v1-accept/T-0007"),
               "--policy", str(tmp_path / "policy.json")])


def reached_job_read(tmp_path):
    with pytest.raises(WorkerFailure) as caught:
        run(tmp_path)
    return caught.value.evidence["phase"] == "job_read"


def test_view_shows_pause_and_role_refuses(policy):
    _, _gateway, tmp_path = policy
    view = role.GATEWAY_VIEW
    view.mkdir(parents=True)
    (view / "PAUSE").touch()
    with pytest.raises(ValueError, match="paused"):
        run(tmp_path)


@pytest.mark.parametrize("name", ["PAUSE", "STOP"])
def test_view_shows_stop_or_pause_even_if_original_path_is_clear(policy, name):
    _, _, tmp_path = policy
    role.GATEWAY_VIEW.mkdir(parents=True)
    (role.GATEWAY_VIEW / name).touch()
    with pytest.raises(ValueError, match="paused"):
        run(tmp_path)


def test_clear_view_lets_the_role_proceed(policy):
    _, _, tmp_path = policy
    role.GATEWAY_VIEW.mkdir(parents=True)
    assert reached_job_read(tmp_path)


def test_without_view_the_original_gateway_is_checked(policy):
    _, gateway, tmp_path = policy
    (gateway / "PAUSE").touch()
    with pytest.raises(ValueError, match="paused"):
        run(tmp_path)
    (gateway / "PAUSE").unlink()
    assert reached_job_read(tmp_path)


def test_unobservable_gateway_without_view_still_fails_closed(policy, monkeypatch):
    _, gateway, tmp_path = policy
    real = Path.exists

    def denied(self, *args, **kwargs):
        if self.parent == gateway:
            raise PermissionError(13, "Permission denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "exists", denied)
    with pytest.raises(PermissionError):
        run(tmp_path)


def test_worker_boundary_reports_unobservable_gateway_as_failure(policy, monkeypatch,
                                                                 capsys):
    _, gateway, tmp_path = policy
    real = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self, *a, **k: (
        (_ for _ in ()).throw(PermissionError(13, "denied", str(self)))
        if self.parent == gateway else real(self, *a, **k)))
    with pytest.raises(SystemExit):
        role.worker_main(["qa", "--job", str(tmp_path / "jobs/dev-v1-accept/T-0007"),
                          "--policy", str(tmp_path / "policy.json")])
    assert '"category": "permission_denied"' in capsys.readouterr().err


def test_drop_in_binds_the_gateway_read_only_at_the_role_view():
    text = (LAB / "fresh_v1/systemd/alfred-development-evidence.conf").read_text()
    line = f"BindReadOnlyPaths=/home/alfred/Alfred/gateway:{role.GATEWAY_VIEW}"
    assert line in text.splitlines()
    assert "BindPaths=" not in text  # Never a writable view.
