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

handoff.44 adds two things the owner can see and use:

- A stall ledger, `stalls.json` next to the state (mode 0644, no secrets: times, legs
  and outcomes only). Each stall opens when a run first suspects it, and closes when the
  watchdog restarts Photon, when inbound recovers by itself, or when the owner clears
  it. Alfred OS shows it under Infrastructure.
- Owner requests, from Alfred OS or from Alfred when Hayden asks: small JSON files in
  REQUESTS (a sticky, group-writable spool; `alfred-photon-requests.path` starts this
  unit as soon as one lands). `clear` restarts Photon now, for the silent stalls no
  check can see, and closes every open stall as cleared by the owner (or records one the
  owner reported). `delete` removes one stall from the list, clearing it first if it is
  still open. Owner restarts have their own limit (OWNER_MIN_INTERVAL, OWNER_MAX_PER_DAY)
  so a stuck button can't loop Photon. Every request is read once, removed, and answered
  in the ledger; who sent it is taken from the file's owner, never from its text.
"""

from __future__ import annotations

import json
import os
import pwd
import re
import stat
import subprocess
import sys
import time
from pathlib import Path

PHOTON = "alfred-photon.service"
HERMES = "alfred-hermes.service"
PORT = 8789
STATE = Path("/var/lib/alfred-photon-watchdog/state.json")
REQUESTS = Path("/var/lib/alfred-photon-requests")
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
OWNER_MIN_INTERVAL = 300  # seconds between owner-requested restarts
OWNER_MAX_PER_DAY = 12
MAX_DELAY = 30  # a request may wait this long, so Alfred's reply goes out before Hermes stops
MAX_REQUEST_BYTES = 2048
MAX_REQUESTS_PER_RUN = 5
KEEP_STALLS = 50  # closed stalls kept in the ledger; the journal keeps everything
KEEP_ANSWERS = 20
REQUEST_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.json")
STALL_ID = re.compile(r"s-[0-9]{10}-[0-9]{1,4}")
SENDERS = {"alfred-os", "alfred"}

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


# ---------------------------------------------------------------------------
# The stall ledger (handoff.44)
# ---------------------------------------------------------------------------


def publish(path: Path, ledger: dict) -> None:
    """Write the ledger readable by the Alfred OS bridges (0644); it holds no secrets."""
    temporary = path.with_name(path.name + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o644)
    try:
        os.fchmod(fd, 0o644)
        os.write(fd, (json.dumps(ledger, sort_keys=True) + "\n").encode())
    finally:
        os.close(fd)
    os.replace(temporary, path)


def _open_stall(ledger: dict) -> dict | None:
    return next((s for s in ledger["stalls"] if s["status"] == "open"), None)


def _new_stall(ledger: dict, now: float, kind: str, legs: dict) -> dict:
    n = 1 + sum(1 for s in ledger["stalls"] if s["id"].startswith("s-%d-" % now))
    stall = {"id": "s-%d-%d" % (now, n), "kind": kind, "started_at": now, "legs": legs,
             "status": "open", "ended_at": None, "cleared_by": None}
    ledger["stalls"].insert(0, stall)
    return stall


def _close(stall: dict, now: float, status: str, by: str | None) -> None:
    stall.update({"status": status, "ended_at": now, "cleared_by": by})


def _trim(ledger: dict) -> dict:
    open_ = [s for s in ledger["stalls"] if s["status"] == "open"]
    closed = [s for s in ledger["stalls"] if s["status"] != "open"][:KEEP_STALLS]
    ledger["stalls"] = open_ + closed
    ledger["answers"] = ledger["answers"][:KEEP_ANSWERS]
    return ledger


def track(ledger: dict, verdict: str, detail: dict, now: float) -> None:
    """Open, update or close the ledger's stall from one run's verdict."""
    stall = _open_stall(ledger)
    legs = {**detail.get("findings", {}), **detail.get("confirmed", {})}
    if "stream_interrupted_for" in detail and "stream" not in legs:
        legs["stream"] = "inbound stream reconnecting for %d seconds" % (
            detail["stream_interrupted_for"])
    if verdict in ("suspect", "withheld", "restart") and legs:
        if stall is None:
            stall = _new_stall(ledger, now, "detected", legs)
        else:
            stall["legs"] = {**stall["legs"], **legs}
        if verdict == "withheld":
            stall["restart_withheld"] = True
        if verdict == "restart":
            _close(stall, now, "cleared", "watchdog")
    elif verdict == "ok" and stall is not None and stall["kind"] == "detected":
        _close(stall, now, "recovered", None)
    ledger["inbound"] = {"ok": "ok", "suspect": "suspect", "withheld": "stalled",
                         "restart": "restarting"}.get(verdict, verdict)
    ledger["checked_at"] = now


def read_ledger(path: Path) -> dict:
    ledger = load(path)
    if ledger.get("schema") != "alfred.photon-stalls/1":
        ledger = {}
    return {"schema": "alfred.photon-stalls/1",
            "stalls": [s for s in ledger.get("stalls", []) if isinstance(s, dict)
                       and isinstance(s.get("id"), str) and s.get("status")],
            "answers": [a for a in ledger.get("answers", []) if isinstance(a, dict)],
            "owner_restarts": [t for t in ledger.get("owner_restarts", [])
                               if isinstance(t, (int, float))],
            "inbound": ledger.get("inbound", "unknown"),
            "checked_at": ledger.get("checked_at")}


# ---------------------------------------------------------------------------
# Owner requests (handoff.44)
# ---------------------------------------------------------------------------


def _sender(uid: int) -> str:
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return "uid %d" % uid


def take_requests(directory: Path) -> list[dict]:
    """Read and remove up to MAX_REQUESTS_PER_RUN request files, oldest first.

    Anything that is not a small regular file with a valid request is removed and
    answered as refused, so a bad file can't keep triggering the path unit.
    """
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    found = []
    for name in names:
        if len(found) >= MAX_REQUESTS_PER_RUN:
            break
        if name.startswith("."):
            continue
        path = directory / name
        request = {"file": name[:64], "action": None, "by": None, "user": None,
                   "stall": None, "delay": 0, "error": None}
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            request["error"] = "unreadable"
        else:
            try:
                info = os.fstat(fd)
                request["user"] = _sender(info.st_uid)
                request["at"] = info.st_mtime
                if not stat.S_ISREG(info.st_mode) or not REQUEST_NAME.fullmatch(name):
                    request["error"] = "not a request file"
                elif info.st_size > MAX_REQUEST_BYTES:
                    request["error"] = "too large"
                else:
                    request.update(parse_request(os.read(fd, MAX_REQUEST_BYTES + 1)))
            finally:
                os.close(fd)
        try:
            path.unlink()
        except OSError:
            pass
        found.append(request)
    return sorted(found, key=lambda r: r.get("at") or 0)


def parse_request(raw: bytes) -> dict:
    try:
        body = json.loads(raw)
    except ValueError:
        return {"error": "not JSON"}
    if not isinstance(body, dict) or body.get("schema") != "alfred.photon-request/1":
        return {"error": "unknown schema"}
    action, by, stall = body.get("action"), body.get("by"), body.get("stall")
    delay = body.get("delay", 0)
    if action not in ("clear", "delete"):
        return {"error": "unknown action"}
    if by not in SENDERS:
        return {"error": "unknown sender"}
    if action == "delete" and not (isinstance(stall, str) and STALL_ID.fullmatch(stall)):
        return {"error": "delete needs a stall id"}
    if stall is not None and not (isinstance(stall, str) and STALL_ID.fullmatch(stall)):
        return {"error": "bad stall id"}
    if type(delay) is not int or not 0 <= delay <= MAX_DELAY:
        return {"error": "delay must be 0 to %d seconds" % MAX_DELAY}
    return {"action": action, "by": by, "stall": stall, "delay": delay}


def owner_may_restart(ledger: dict, now: float) -> str | None:
    """Why an owner restart is refused right now, or None."""
    recent = [t for t in ledger["owner_restarts"] if now - t < 86400]
    if recent and now - recent[-1] < OWNER_MIN_INTERVAL:
        return "Photon was restarted %d seconds ago; try again in %d" % (
            now - recent[-1], OWNER_MIN_INTERVAL - (now - recent[-1]))
    if len(recent) >= OWNER_MAX_PER_DAY:
        return "%d owner restarts today already" % OWNER_MAX_PER_DAY
    return None


def handle_requests(ledger: dict, requests: list[dict], now: float, sleep) -> bool:
    """Apply owner requests to the ledger; True when Photon should restart now."""
    restart, delay = False, 0
    for request in requests:
        answer = {"file": request["file"], "action": request["action"], "by": request["by"],
                  "user": request["user"], "stall": request["stall"], "received_at": now}
        stall = next((s for s in ledger["stalls"] if s["id"] == request["stall"]), None)
        if request["error"]:
            answer.update(outcome="refused", detail=request["error"])
        elif request["stall"] and stall is None:
            answer.update(outcome="refused", detail="no such stall")
        elif request["action"] == "delete" and stall["status"] != "open":
            ledger["stalls"].remove(stall)
            answer.update(outcome="deleted", detail="removed from the list")
        elif not restart and (why := owner_may_restart(ledger, now)) is not None:
            answer.update(outcome="refused", detail=why)
        else:
            # Clear, or delete a stall that is still open: restart Photon (once per run).
            if not restart:
                restart = True
                who = request["by"]
                open_ = [s for s in ledger["stalls"] if s["status"] == "open"]
                if not open_:
                    open_ = [_new_stall(ledger, now, "reported",
                                        {"owner": "texts were not reaching Alfred"})]
                for s in open_:
                    _close(s, now, "cleared", who)
                answer["stall"] = request["stall"] or open_[0]["id"]
            delay = max(delay, request["delay"])
            if request["action"] == "delete" and stall in ledger["stalls"]:
                ledger["stalls"].remove(stall)
            answer.update(outcome="cleared", detail="restarting Photon")
        log("owner_request", **{k: v for k, v in answer.items() if k != "received_at"})
        ledger["answers"].insert(0, answer)
    if restart:
        ledger["owner_restarts"] = [t for t in ledger["owner_restarts"]
                                    if now - t < 86400] + [now]
        if delay:
            sleep(delay)
    return restart


def check(now: float | None = None, monotonic: float | None = None,
          state_path: Path = STATE, requests_dir: Path = REQUESTS, sleep=time.sleep) -> str:
    now = time.time() if now is None else now
    monotonic = time.monotonic() if monotonic is None else monotonic
    stalls_path = state_path.with_name("stalls.json")
    ledger = read_ledger(stalls_path)
    requests = take_requests(requests_dir)
    if requests and handle_requests(ledger, requests, now, sleep):
        publish(stalls_path, _trim({**ledger, "inbound": "restarting", "checked_at": now}))
        log("owner_restarting", unit=PHOTON)
        try:
            run([SYSTEMCTL, "restart", PHOTON])
            log("restarted", unit=PHOTON, photon=unit(PHOTON).get("ActiveState"),
                hermes=unit(HERMES).get("ActiveState"), by="owner")
        except (subprocess.SubprocessError, OSError) as error:
            log("restart_failed", unit=PHOTON, error=type(error).__name__, by="owner")
        save(state_path, {**load(state_path), "last": "owner_restart", "seen": {}})
        return "owner_restart"
    verdict = _check(now, monotonic, state_path, ledger)
    publish(stalls_path, _trim(ledger))
    return verdict


def _check(now: float, monotonic: float, state_path: Path, ledger: dict) -> str:
    state = load(state_path)
    photon, hermes = unit(PHOTON), unit(HERMES)
    if photon.get("ActiveState") != "active" or hermes.get("ActiveState") != "active":
        if state.get("last") != "inactive":
            log("units_not_active", photon=photon.get("ActiveState"),
                hermes=hermes.get("ActiveState"), action="none; systemd restarts them")
        save(state_path, {**state, "last": "inactive", "seen": {}})
        ledger.update(inbound="inactive", checked_at=now)
        return "inactive"
    if monotonic - int(photon.get("ActiveEnterTimestampMonotonic") or 0) / 1e6 < GRACE:
        ledger.update(inbound="starting", checked_at=now)
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
    track(ledger, verdict, detail, now)
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
