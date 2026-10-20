"""handoff.44: the Photon watchdog's stall list and the owner's clear and delete requests."""

import json
import os

import pytest

from fresh_v1 import photon_watchdog as w
from test_photon_watchdog import HEALTHY_PHOTON, NOW, Host, interrupted

SILENT = HEALTHY_PHOTON.replace("lastrcv:3783", "lastrcv:900000")


@pytest.fixture
def host(monkeypatch):
    def install(**kwargs):
        fake = Host(**kwargs)
        monkeypatch.setattr(w, "run", fake)
        return fake
    return install


@pytest.fixture
def paths(tmp_path):
    spool = tmp_path / "requests"
    spool.mkdir()
    return tmp_path / "state" / "state.json", spool


def ledger(state):
    raw = state.with_name("stalls.json")
    assert raw.stat().st_mode & 0o777 == 0o644
    return json.loads(raw.read_bytes())


def ask(spool, name="1-a.json", **body):
    body = {"schema": "alfred.photon-request/1", "action": "clear", "by": "alfred-os",
            "stall": None, "delay": 0, **body}
    (spool / name).write_text(json.dumps(body))


def check(state, spool, at, mono, sleeps=None):
    state.parent.mkdir(exist_ok=True)
    return w.check(at, mono, state, spool, (sleeps if sleeps is not None else []).append)


def test_a_stall_opens_when_suspected_and_closes_when_the_watchdog_restarts(host, paths):
    state, spool = paths
    host(photon_ss=SILENT)
    assert check(state, spool, NOW, 5000) == "suspect"
    first = ledger(state)
    assert first["inbound"] == "suspect"
    [stall] = first["stalls"]
    assert stall["status"] == "open" and stall["kind"] == "detected"
    assert "upstream" in stall["legs"]
    assert check(state, spool, NOW + 120, 5120) == "restart"
    [stall] = ledger(state)["stalls"]
    assert stall["status"] == "cleared" and stall["cleared_by"] == "watchdog"


def test_a_stall_that_goes_away_on_its_own_is_recovered(host, paths):
    state, spool = paths
    host(photon_ss=SILENT)
    check(state, spool, NOW, 5000)
    host()
    assert check(state, spool, NOW + 120, 5120) == "ok"
    [stall] = ledger(state)["stalls"]
    assert stall["status"] == "recovered" and ledger(state)["inbound"] == "ok"


def test_a_stuck_stream_counts_as_a_leg(host, paths):
    state, spool = paths
    host(journal=interrupted(NOW - 100))
    assert check(state, spool, NOW, 5000) == "suspect"
    assert "stream" in ledger(state)["stalls"][0]["legs"]


def test_the_owner_clears_a_silent_stall_nothing_detected(host, paths):
    state, spool = paths
    fake = host()
    check(state, spool, NOW, 5000)
    ask(spool, by="alfred", delay=20)
    sleeps = []
    assert check(state, spool, NOW + 30, 5030, sleeps) == "owner_restart"
    assert fake.restarts() == [[w.SYSTEMCTL, "restart", w.PHOTON]]
    assert sleeps == [20]
    assert list(spool.iterdir()) == []
    data = ledger(state)
    [stall] = data["stalls"]
    assert stall["kind"] == "reported" and stall["status"] == "cleared"
    assert stall["cleared_by"] == "alfred"
    [answer] = data["answers"]
    assert answer["outcome"] == "cleared" and answer["stall"] == stall["id"]
    assert answer["user"]  # taken from the file's owner, never from its text


def test_owner_restarts_are_limited(host, paths):
    state, spool = paths
    fake = host()
    ask(spool)
    check(state, spool, NOW, 5000)
    ask(spool, name="2-b.json")
    assert check(state, spool, NOW + 60, 5060) != "owner_restart"
    assert len(fake.restarts()) == 1
    assert ledger(state)["answers"][0]["outcome"] == "refused"
    ask(spool, name="3-c.json")
    assert check(state, spool, NOW + 60 + w.OWNER_MIN_INTERVAL, 9000) == "owner_restart"
    assert len(fake.restarts()) == 2


def test_two_requests_in_one_run_restart_once(host, paths):
    state, spool = paths
    fake = host()
    ask(spool, name="1-a.json")
    ask(spool, name="2-b.json", by="alfred")
    assert check(state, spool, NOW, 5000) == "owner_restart"
    assert len(fake.restarts()) == 1
    assert [a["outcome"] for a in ledger(state)["answers"]] == ["cleared", "cleared"]


def test_delete_removes_a_closed_stall_and_clears_an_open_one(host, paths):
    state, spool = paths
    fake = host(photon_ss=SILENT)
    check(state, spool, NOW, 5000)
    check(state, spool, NOW + 120, 5120)  # the watchdog's restart closes it
    closed = ledger(state)["stalls"][0]["id"]
    ask(spool, action="delete", stall=closed)
    check(state, spool, NOW + 240, 5240)  # still silent afterwards: a new stall opens
    data = ledger(state)
    assert data["answers"][0]["outcome"] == "deleted"
    assert [s["status"] for s in data["stalls"]] == ["open"]
    assert len(fake.restarts()) == 1
    # Deleting the open one restarts Photon and takes it off the list.
    ask(spool, name="9-z.json", action="delete", stall=data["stalls"][0]["id"])
    assert check(state, spool, NOW + 360, 5360) == "owner_restart"
    assert ledger(state)["stalls"] == []
    assert len(fake.restarts()) == 2


@pytest.mark.parametrize("body,detail", [
    ({"action": "reboot"}, "unknown action"),
    ({"by": "mallory"}, "unknown sender"),
    ({"action": "delete"}, "delete needs a stall id"),
    ({"delay": 999}, "delay must be 0 to 30 seconds"),
    ({"schema": "x"}, "unknown schema"),
])
def test_bad_requests_are_removed_and_refused(host, paths, body, detail):
    state, spool = paths
    fake = host()
    ask(spool, **body)
    check(state, spool, NOW, 5000)
    assert fake.restarts() == [] and list(spool.iterdir()) == []
    assert ledger(state)["answers"][0] == {**ledger(state)["answers"][0],
                                           "outcome": "refused", "detail": detail}


def test_symlinks_and_odd_names_are_refused(host, paths, tmp_path):
    state, spool = paths
    fake = host()
    target = tmp_path / "elsewhere.json"
    target.write_text("{}")
    os.symlink(target, spool / "1-link.json")
    (spool / "bad name!.json").write_text("{}")
    (spool / ".pending.json").write_text("{}")  # still being written: left alone
    check(state, spool, NOW, 5000)
    assert fake.restarts() == [] and target.exists()
    assert sorted(p.name for p in spool.iterdir()) == [".pending.json"]
    assert {a["outcome"] for a in ledger(state)["answers"]} == {"refused"}


def test_unknown_stall_is_refused(host, paths):
    state, spool = paths
    host()
    ask(spool, action="delete", stall="s-1800000000-1")
    check(state, spool, NOW, 5000)
    assert ledger(state)["answers"][0]["detail"] == "no such stall"
