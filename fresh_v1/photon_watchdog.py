"""Photon inbound watchdog: restart alfred-photon.service only when inbound has stalled.

On 2026-10-19/20 Hayden's texts stopped reaching Alfred while alfred-photon.service and
alfred-hermes.service both stayed `active`; `systemctl restart alfred-photon.service`
(which also restarts Hermes, through its Requires=) recovered it each time. A separate
root oneshot (alfred-photon-watchdog.timer, every two minutes) looks for stalls that a
quiet line never shows, and restarts Photon only when one is confirmed:

- stream: the sidecar logged `[spectrum.stream] WARN stream interrupted; reconnecting`
  for the `imessage.messages` stream and no `stream recovered` for it since, for
  STREAM_STUCK seconds. A healthy reconnect takes about a second; on 2026-10-19 the
  stream stayed in this state from 04:46 to 21:53 and no texts arrived.
- upstream: the sidecar holds no established connection to Photon, or its connection
  has received nothing for UPSTREAM_SILENT seconds. A live subscription always holds one
  connection, and Photon sends on it every few seconds even when no one is texting
  (about 1,000 packets in the 1 h 53 min after the 2026-10-20 00:20 restart, never
  more than 17 s apart in a 15-minute sample), so a silent connection is a half-open one.
- consumer: the sidecar has no Hermes `/inbound` connection on 127.0.0.1:8789 whose
  25-second heartbeat is fresh. Without a consumer the sidecar stops pulling inbound.

It also logs, without acting on it, when Hermes leaves bytes unread on its `/inbound`
connection on two runs in a row, as evidence for the next investigation.

Everything is read without credentials: `ss` socket tables filtered by each unit's
cgroup, and the journal of Photon's current run (its invocation ID). Nothing is judged
while either unit is not active (systemd restarts those itself) or within GRACE seconds
of Photon starting. A socket finding counts only when CONFIRM consecutive runs see it.
Restarts are rate-limited: at most one per MIN_INTERVAL and MAX_PER_DAY a day; past that
it only logs that the owner is needed. Every finding, restart and refusal is one JSON
line in the journal under `alfred-photon-watchdog`; a healthy run logs only when the
state changes, plus one line an hour.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PHOTON = "alfred-photon.service"
HERMES = "alfred-hermes.service"
PORT = 8789
STATE = Path("/var/lib/alfred-photon-watchdog/state.json")
SYSTEMCTL = "/usr/bin/systemctl"
JOURNALCTL = "/usr/bin/journalctl"
SS = "/usr/bin/ss"

GRACE = 180  # seconds after Photon starts before anything is judged
STREAM_STUCK = 600  # an interrupted inbound stream with no recovery for this long
UPSTREAM_SILENT = 300  # Photon's connection received nothing for this long
HEARTBEAT_STALE = 90  # the sidecar heartbeats its consumer every 25 seconds
CONFIRM = 2  # consecutive runs that must see the same socket finding
MIN_INTERVAL = 1800  # seconds between watchdog restarts
MAX_PER_DAY = 4
REPORT_EVERY = 3600  # a healthy watchdog says so once an hour
RESTART_TIMEOUT = 180
MESSAGES_LABEL = "imessage.messages"

INTERRUPTED = re.compile(
    r"\[spectrum\.stream\] (WARN|ERROR) stream (interrupted|persistently failing)")
RECOVERED = re.compile(r"\[spectrum\.stream\] INFO stream recovered")
LABEL = re.compile(r"'spectrum\.stream\.label': '([^']*)'")
TIMER = re.compile(r"\b(lastsnd|lastrcv):(\d+)\b")


def log(event: str, **detail) -> None:
    print(json.dumps({"event": event, **detail}, sort_keys=True), flush=True)


def run(argv: list[str]) -> str:
    # A restart waits for Hermes to stop first, which may take its TimeoutStopSec (70 s).
    timeout = RESTART_TIMEOUT if argv[1:2] == ["restart"] else 30
    return subprocess.run(argv, check=True, capture_output=True, text=True,
                          timeout=timeout).stdout


def unit(name: str) -> dict:
    out = run([SYSTEMCTL, "show", name, "-p", "ActiveState", "-p", "InvocationID",
               "-p", "ActiveEnterTimestampMonotonic"])
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def sockets(name: str) -> list[dict]:
    return parse_ss(run([SS, "-Htni", "state", "established",
                         "cgroup", "/system.slice/" + name]))


def endpoint(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    return host.strip("[]"), int(port)


def parse_ss(text: str) -> list[dict]:
    """`ss -Htni state established`: a socket line, then an indented TCP info line."""
    found = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line[0] in " \t":
            if found:
                found[-1].update({k: int(v) for k, v in TIMER.findall(line)})
            continue
        fields = line.split()
        if len(fields) < 4 or not fields[0].isdigit():
            continue
        found.append({"recv_q": int(fields[0]), "local": endpoint(fields[2]),
                      "peer": endpoint(fields[3])})
    return found


def loopback(host: str) -> bool:
    return host == "::1" or host.startswith(("127.", "::ffff:127."))


def socket_findings(photon: list[dict]) -> dict:
    """Findings from the sidecar's own sockets; {} when inbound looks healthy."""
    consumers = [s for s in photon if s["local"][1] == PORT and loopback(s["peer"][0])]
    fresh = [s for s in consumers if s.get("lastsnd", 10**9) <= HEARTBEAT_STALE * 1000]
    upstream = [s for s in photon if not loopback(s["peer"][0])]
    findings = {}
    if not upstream:
        findings["upstream"] = "no connection to Photon"
    elif min(s.get("lastrcv", 10**9) for s in upstream) > UPSTREAM_SILENT * 1000:
        findings["upstream"] = "Photon connection silent for %d seconds" % (
            min(s.get("lastrcv", 10**9) for s in upstream) // 1000)
    if not fresh:
        findings["consumer"] = ("no Hermes /inbound connection" if not consumers
                                else "the /inbound heartbeat stopped")
    return findings


def unread(hermes: list[dict]) -> int:
    """Bytes Hermes has not read from its /inbound connection."""
    return sum(s["recv_q"] for s in hermes if s["peer"][1] == PORT and loopback(s["peer"][0]))


def stream_stuck_since(entries: list[tuple[float, str]]) -> float | None:
    """When the inbound messages stream was interrupted without recovering, else None.

    `entries` are (realtime seconds, message) for this run of the unit, in order. The SDK
    logs each stream event as a header line followed by one line per field.
    """
    since = None
    current = None  # (kind, at) of the event block being read
    for at, message in entries:
        if INTERRUPTED.search(message):
            current = ("interrupted", at)
        elif RECOVERED.search(message):
            current = ("recovered", at)
        elif current is not None and (label := LABEL.search(message)):
            if label.group(1).split(":", 1)[0] == MESSAGES_LABEL:
                kind, block_at = current
                if kind == "recovered":
                    since = None
                elif since is None:
                    since = block_at
            current = None
    return since


def journal(invocation: str) -> list[tuple[float, str]]:
    out = run([JOURNALCTL, "_SYSTEMD_INVOCATION_ID=" + invocation, "-o", "json",
               "--no-pager", "--output-fields=MESSAGE,__REALTIME_TIMESTAMP"])
    entries = []
    for line in out.splitlines():
        try:
            record = json.loads(line)
            entries.append((int(record["__REALTIME_TIMESTAMP"]) / 1e6, record["MESSAGE"]))
        except (ValueError, KeyError, TypeError):
            continue
    return [(at, message) for at, message in entries if isinstance(message, str)]


def load(path: Path) -> dict:
    try:
        state = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def save(path: Path, state: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, sort_keys=True) + "\n")
    os.replace(temporary, path)


def decide(state: dict, invocation: str, findings: dict, stuck_since: float | None,
           now: float) -> tuple[str, dict, dict]:
    """(verdict, confirmed findings, new state); verdict is ok, suspect, restart or withheld."""
    restarts = [t for t in state.get("restarts", []) if now - t < 86400]
    seen = dict(state.get("seen", {})) if state.get("invocation") == invocation else {}
    seen = {name: seen.get(name, 0) + 1 for name in findings}
    confirmed = {name: findings[name] for name, count in seen.items() if count >= CONFIRM}
    if stuck_since is not None and now - stuck_since >= STREAM_STUCK:
        confirmed["stream"] = "inbound stream reconnecting for %d seconds" % (
            now - stuck_since)
    new = {**state, "invocation": invocation, "seen": seen, "restarts": restarts}
    if not confirmed:
        return ("suspect" if findings or stuck_since is not None else "ok"), confirmed, new
    if (restarts and now - restarts[-1] < MIN_INTERVAL) or len(restarts) >= MAX_PER_DAY:
        return "withheld", confirmed, new
    return "restart", confirmed, {**new, "seen": {}, "restarts": restarts + [now]}


def check(now: float | None = None, monotonic: float | None = None,
          state_path: Path = STATE) -> str:
    now = time.time() if now is None else now
    monotonic = time.monotonic() if monotonic is None else monotonic
    state = load(state_path)
    photon, hermes = unit(PHOTON), unit(HERMES)
    if photon.get("ActiveState") != "active" or hermes.get("ActiveState") != "active":
        if state.get("last") != "inactive":
            log("units_not_active", photon=photon.get("ActiveState"),
                hermes=hermes.get("ActiveState"), action="none; systemd restarts them")
        save(state_path, {**state, "last": "inactive", "seen": {}})
        return "inactive"
    if monotonic - int(photon.get("ActiveEnterTimestampMonotonic") or 0) / 1e6 < GRACE:
        return "grace"
    invocation = photon.get("InvocationID", "")
    findings = socket_findings(sockets(PHOTON))
    stuck_since = stream_stuck_since(journal(invocation)) if invocation else None
    verdict, confirmed, new = decide(state, invocation, findings, stuck_since, now)
    detail = {"findings": findings, "confirmed": confirmed}
    if stuck_since is not None:
        detail["stream_interrupted_for"] = int(now - stuck_since)
    pending = unread(sockets(HERMES))
    if pending and state.get("unread"):
        detail["hermes_unread_bytes"] = pending  # evidence only; never acted on
    new["unread"] = pending
    if verdict == "restart":
        log("stall_confirmed_restarting", unit=PHOTON, **detail)
        save(state_path, {**new, "last": verdict, "detail": detail})
        try:
            run([SYSTEMCTL, "restart", PHOTON])
            log("restarted", unit=PHOTON, photon=unit(PHOTON).get("ActiveState"),
                hermes=unit(HERMES).get("ActiveState"))
        except (subprocess.SubprocessError, OSError) as error:
            log("restart_failed", unit=PHOTON, error=type(error).__name__)
        return verdict
    if verdict == "withheld":
        if state.get("last") != verdict:
            log("stall_confirmed_restart_withheld", unit=PHOTON,
                reason="at most one restart per %d minutes and %d a day"
                % (MIN_INTERVAL // 60, MAX_PER_DAY),
                owner="sudo systemctl restart " + PHOTON, **detail)
    elif verdict == "suspect" or "hermes_unread_bytes" in detail:
        if state.get("last") != verdict or detail != state.get("detail"):
            log("stall_suspected", **detail)
    elif state.get("last") != verdict or now - state.get("reported", 0) >= REPORT_EVERY:
        log("inbound_ok", restarts_last_day=len(new["restarts"]))
        new["reported"] = now
    save(state_path, {**new, "last": verdict, "detail": detail})
    return verdict


def main() -> int:
    try:
        check()
    except (subprocess.SubprocessError, OSError, ValueError) as error:
        log("check_failed", error=type(error).__name__, detail=str(error)[:200])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
