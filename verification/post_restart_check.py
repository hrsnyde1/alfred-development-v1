"""Read-only Gate 5 check after the Phase C restart. Never writes, restarts or sends.

Run as alfred (journal access comes from the adm group) from the merged checkout:

    /usr/bin/python3 -I -B verification/post_restart_check.py

It verifies the seven Phase B files still carry their installed digests, that
Intake, Photon and Hermes are running processes started *after* those files were
installed (so the new code is loaded), that PAUSE is still in place and STOP is
absent, and counts error-priority journal lines since each start. Only counts and
timestamps are printed, never log text. An ordinary Alfred chat is still checked
by hand on the phone.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
MANIFEST = (
    HERE
    / "dist/alfred-fresh-v1-1.0.1-development-handoff.2/development_challenge"
    / "installed-after.sha256"
)
GATEWAY = Path("/home/alfred/Alfred/gateway")
UNITS = (
    "alfred-development-intake.service",
    "alfred-photon.service",
    "alfred-hermes.service",
)
ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "SYSTEMD_PAGER": ""}


def run(argv: list[str]) -> str:
    return subprocess.run(
        argv, check=True, capture_output=True, text=True, timeout=30, env=ENV
    ).stdout


def digest(path: Path) -> tuple[str, float]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode):
            return "not-regular", info.st_mtime
        return hashlib.sha256(stream.read()).hexdigest(), info.st_mtime


def installed(manifest: Path) -> tuple[dict, float]:
    files, newest = {}, 0.0
    for line in manifest.read_text().splitlines():
        expected, name = line.split("  ", 1)
        try:
            actual, mtime = digest(Path(name))
        except OSError as exc:
            files[name] = f"unreadable: errno={exc.errno}"
            continue
        files[name] = "OK" if actual == expected else "MISMATCH"
        newest = max(newest, mtime)
    return files, newest


def unit(name: str, installed_at: float, now: float) -> dict:
    raw = run(
        [
            "/usr/bin/systemctl",
            "show",
            "--timestamp=unix",
            "-p",
            "ActiveState,SubState,ExecMainStartTimestamp,NRestarts",
            name,
        ]
    )
    props = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    stamp = props.get("ExecMainStartTimestamp", "")
    started = float(stamp[1:]) if stamp.startswith("@") else None
    record = {
        "active": props.get("ActiveState") == "active"
        and props.get("SubState") == "running",
        "started_after_install": started is not None and started > installed_at,
        "uptime_seconds": None if started is None else int(now - started),
        "automatic_restarts": int(props.get("NRestarts") or 0),
    }
    if started is not None:
        try:
            lines = run(
                [
                    "/usr/bin/journalctl",
                    "-u",
                    name,
                    "-p",
                    "err",
                    "--since",
                    f"@{int(started)}",
                    "-q",
                    "-o",
                    "cat",
                    "--no-pager",
                ]
            )
            record["errors_since_start"] = len(lines.splitlines())
        except (OSError, subprocess.SubprocessError):
            record["errors_since_start"] = "UNAVAILABLE"
    return record


def check(manifest: Path, gateway: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    files, installed_at = installed(manifest)
    units = {name: unit(name, installed_at, now) for name in UNITS}
    files_ok = len(files) == 7 and all(v == "OK" for v in files.values())
    pause = (gateway / "PAUSE").is_file()
    stop = (gateway / "STOP").exists()
    if not files_ok or stop or not pause:
        overall = "FAIL"
    elif not all(u["started_after_install"] for u in units.values()):
        overall = "NOT_RESTARTED"
    elif not all(
        u["active"]
        and u["automatic_restarts"] == 0
        and u.get("errors_since_start") == 0
        for u in units.values()
    ):
        overall = "FAIL"
    else:
        overall = "PASS"
    return {
        "schema": "alfred.phase-c-check/1",
        "installed_files": files,
        "installed_at": int(installed_at),
        "units": units,
        "pause_present": pause,
        "stop_present": stop,
        "manual_check": "send an ordinary (non-development) message to Alfred",
        "overall": overall,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--gateway", type=Path, default=GATEWAY)
    args = parser.parse_args(argv)
    try:
        report = check(args.manifest, args.gateway)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"overall": "UNAVAILABLE", "reason": type(exc).__name__}))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["overall"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
