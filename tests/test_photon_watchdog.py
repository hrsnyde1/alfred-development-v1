"""handoff.43: the Photon inbound watchdog restarts only on a confirmed, rate-limited stall."""

import json

import pytest

from fresh_v1 import photon_watchdog as w

NOW = 1_800_000_000.0
HEALTHY_PHOTON = """\
0      0          127.0.0.1:8789      127.0.0.1:35432
\t cubic wscale:7,7 rto:201 bytes_sent:11103 lastsnd:15461 lastrcv:6865872 lastack:15461
0      0      192.168.50.81:56744 184.169.251.5:443
\t cubic wscale:13,7 rto:237 data_segs_in:1030 lastsnd:3910 lastrcv:3783 lastack:3783
"""
HEALTHY_HERMES = """\
0      0          127.0.0.1:35432     127.0.0.1:8789
\t cubic wscale:7,7 lastsnd:6865872 lastrcv:15461 lastack:15461
"""


def interrupted(at, label="imessage.messages:shared", stream_id="77d1"):
    return [
        (at, "[spectrum.stream] WARN stream interrupted; reconnecting {"),
        (at, f"  'spectrum.stream.id': '{stream_id}',"),
        (at, f"  'spectrum.stream.label': '{label}',"),
        (at, "  'spectrum.stream.phase': 'live',"),
        (at, "} RetryableStreamError: Live stream ended"),
    ]


def recovered(at, label="imessage.messages:shared"):
    return [
        (at, "[spectrum.stream] INFO stream recovered {"),
        (at, "  'spectrum.stream.id': '77d1',"),
        (at, f"  'spectrum.stream.label': '{label}',"),
        (at, "}"),
    ]


def test_a_healthy_quiet_line_has_no_findings():
    assert w.socket_findings(w.parse_ss(HEALTHY_PHOTON)) == {}
    assert w.unread(w.parse_ss(HEALTHY_HERMES)) == 0


def test_socket_findings():
    no_consumer = w.parse_ss(HEALTHY_PHOTON.splitlines(True)[2] + HEALTHY_PHOTON.splitlines(True)[3])
    assert set(w.socket_findings(no_consumer)) == {"consumer"}
    stale = w.parse_ss(HEALTHY_PHOTON.replace("lastsnd:15461", "lastsnd:200000"))
    assert w.socket_findings(stale) == {"consumer": "the /inbound heartbeat stopped"}
    no_upstream = w.parse_ss("".join(HEALTHY_PHOTON.splitlines(True)[:2]))
    assert w.socket_findings(no_upstream) == {"upstream": "no connection to Photon"}
    silent = w.parse_ss(HEALTHY_PHOTON.replace("lastrcv:3783", "lastrcv:400000"))
    assert set(w.socket_findings(silent)) == {"upstream"}
    assert w.unread(w.parse_ss(HEALTHY_HERMES.replace("0      0  ", "12     0  ", 1))) == 12


def test_the_2026_10_19_outage_is_a_stuck_stream_and_a_quick_reconnect_is_not():
    polls = interrupted(NOW - 5000, label="imessage.polls:shared", stream_id="9fd8")
    entries = interrupted(NOW - 5000) + interrupted(NOW - 4999) + polls
    assert w.stream_stuck_since(entries) == NOW - 5000
    assert w.stream_stuck_since(entries + recovered(NOW - 10)) is None
    # Only the polls stream interrupted: not inbound messages.
    assert w.stream_stuck_since(polls) is None
    # A shutdown's "inbound stream ended" line is not an interruption.
    assert w.stream_stuck_since([(NOW, "photon-sidecar: inbound stream ended — re-subscribing")]) is None


def test_findings_need_two_runs_and_restarts_are_rate_limited():
    finding = {"upstream": "no connection to Photon"}
    verdict, confirmed, state = w.decide({}, "run-1", finding, None, NOW)
    assert (verdict, confirmed) == ("suspect", {})
    # A different run of the unit starts counting again.
    assert w.decide(state, "run-2", finding, None, NOW + 120)[0] == "suspect"
    verdict, confirmed, state = w.decide(state, "run-1", finding, None, NOW + 120)
    assert verdict == "restart" and confirmed == finding
    assert state["restarts"] == [NOW + 120] and state["seen"] == {}
    # Confirmed again within MIN_INTERVAL: withheld.
    state = {**state, "seen": {"upstream": 1}}
    assert w.decide(state, "run-1", finding, None, NOW + 600)[0] == "withheld"
    # A finding that clears resets its count.
    _, _, cleared = w.decide({"invocation": "run-1", "seen": {"upstream": 1}}, "run-1", {}, None, NOW)
    assert cleared["seen"] == {}


def test_a_stuck_stream_restarts_once_it_has_lasted_long_enough():
    assert w.decide({}, "run-1", {}, NOW - 60, NOW)[0] == "suspect"
    verdict, confirmed, _ = w.decide({}, "run-1", {}, NOW - w.STREAM_STUCK, NOW)
    assert verdict == "restart" and "stream" in confirmed


def test_at_most_max_per_day():
    day = [NOW - 80000 + i * w.MIN_INTERVAL for i in range(w.MAX_PER_DAY)]
    assert w.decide({"restarts": day}, "r", {}, NOW - 9999, NOW)[0] == "withheld"
    # Restarts older than a day no longer count.
    old = [NOW - 90000 - i for i in range(w.MAX_PER_DAY)]
    assert w.decide({"restarts": old}, "r", {}, NOW - 9999, NOW)[0] == "restart"


class Host:
    """systemctl, journalctl and ss doubles; records every command."""

    def __init__(self, photon_ss=HEALTHY_PHOTON, hermes_ss=HEALTHY_HERMES, journal=(),
                 photon_state="active", started=1000.0):
        self.photon_ss, self.hermes_ss, self.entries = photon_ss, hermes_ss, list(journal)
        self.photon_state, self.started, self.calls = photon_state, started, []

    def __call__(self, argv):
        self.calls.append(argv)
        if argv[:2] == [w.SYSTEMCTL, "show"]:
            state = self.photon_state if argv[2] == w.PHOTON else "active"
            return (f"ActiveState={state}\nInvocationID=run-1\n"
                    f"ActiveEnterTimestampMonotonic={int(self.started * 1e6)}\n")
        if argv[0] == w.SS:
            return self.photon_ss if argv[-1].endswith(w.PHOTON) else self.hermes_ss
        if argv[0] == w.JOURNALCTL:
            assert argv[1] == "_SYSTEMD_INVOCATION_ID=run-1"
            return "".join(json.dumps({"MESSAGE": m, "__REALTIME_TIMESTAMP": str(int(t * 1e6))})
                           + "\n" for t, m in self.entries)
        if argv[:2] == [w.SYSTEMCTL, "restart"]:
            assert argv[2] == w.PHOTON
            return ""
        raise AssertionError(argv)

    def restarts(self):
        return [c for c in self.calls if c[:2] == [w.SYSTEMCTL, "restart"]]


@pytest.fixture
def host(monkeypatch):
    def install(**kwargs):
        fake = Host(**kwargs)
        monkeypatch.setattr(w, "run", fake)
        return fake
    return install


def events(capsys):
    return [json.loads(line)["event"] for line in capsys.readouterr().out.splitlines()]


def test_a_quiet_healthy_host_is_never_restarted(host, tmp_path, capsys):
    fake = host()
    state = tmp_path / "state.json"
    for i in range(31):
        assert w.check(NOW + i * 120, 5000 + i * 120, state) == "ok"
    assert fake.restarts() == []
    assert events(capsys) == ["inbound_ok"] * 2  # the first run, then an hour later


def test_a_half_open_stream_is_restarted_after_two_runs(host, tmp_path, capsys):
    fake = host(photon_ss=HEALTHY_PHOTON.replace("lastrcv:3783", "lastrcv:900000"))
    state = tmp_path / "state.json"
    assert w.check(NOW, 5000, state) == "suspect"
    assert fake.restarts() == []
    assert w.check(NOW + 120, 5120, state) == "restart"
    assert fake.restarts() == [[w.SYSTEMCTL, "restart", w.PHOTON]]
    assert events(capsys) == ["stall_suspected", "stall_confirmed_restarting", "restarted"]
    # Still stalled after the restart: withheld, logged once, owner named.
    w.check(NOW + 240, 5240, state)
    assert w.check(NOW + 360, 5360, state) == "withheld"
    w.check(NOW + 480, 5480, state)
    assert len(fake.restarts()) == 1
    out = capsys.readouterr().out
    assert out.count("stall_confirmed_restart_withheld") == 1
    assert "sudo systemctl restart alfred-photon.service" in out


def test_the_stream_outage_from_the_journal_restarts(host, tmp_path):
    fake = host(journal=interrupted(NOW - 700))
    assert w.check(NOW, 5000, tmp_path / "state.json") == "restart"
    assert len(fake.restarts()) == 1


def test_nothing_is_judged_while_starting_or_inactive(host, tmp_path, capsys):
    stalled = HEALTHY_PHOTON.replace("lastrcv:3783", "lastrcv:900000")
    fake = host(photon_ss=stalled, started=4900.0)
    assert w.check(NOW, 5000, tmp_path / "state.json") == "grace"
    fake = host(photon_ss=stalled, photon_state="activating")
    assert w.check(NOW, 5000, tmp_path / "state.json") == "inactive"
    assert w.check(NOW + 120, 5120, tmp_path / "state.json") == "inactive"
    assert fake.restarts() == []
    assert events(capsys) == ["units_not_active"]


def test_hermes_leaving_bytes_unread_is_logged_never_acted_on(host, tmp_path, capsys):
    fake = host(hermes_ss=HEALTHY_HERMES.replace("0      0  ", "40     0  ", 1))
    state = tmp_path / "state.json"
    assert w.check(NOW, 5000, state) == "ok"
    assert w.check(NOW + 120, 5120, state) == "ok"
    assert fake.restarts() == []
    out = capsys.readouterr().out
    assert '"hermes_unread_bytes": 40' in out


def test_a_failing_command_is_logged_not_raised(monkeypatch, capsys):
    def broken(argv):
        raise FileNotFoundError(argv[0])
    monkeypatch.setattr(w, "run", broken)
    assert w.main() == 1
    assert events(capsys) == ["check_failed"]


def test_a_restart_may_wait_for_hermes_to_stop(monkeypatch):
    seen = []

    class Done:
        stdout = ""

    def fake_run(argv, **kwargs):
        seen.append((argv[1], kwargs["timeout"]))
        return Done()
    monkeypatch.setattr(w.subprocess, "run", fake_run)
    w.run([w.SYSTEMCTL, "restart", w.PHOTON])
    w.run([w.SYSTEMCTL, "show", w.PHOTON])
    assert seen == [("restart", w.RESTART_TIMEOUT), ("show", 30)]
    assert w.RESTART_TIMEOUT > 70 + 15  # Hermes' and Photon's TimeoutStopSec
