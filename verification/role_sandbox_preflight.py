"""Gate 6 preflight: every fresh V1 role inside the real Evidence sandbox. Read-only.

Run as root from the merged checkout (PAUSE may stay in place):

    /usr/bin/python3 -I -B verification/role_sandbox_preflight.py

Before handoff.5 is installed, `--with-gateway-view` adds just its read-only gateway
view mount to the transient units, to preview the whole environment in one run.

For each role identity it starts one transient unit carrying the sandbox settings of
the *installed* alfred-development-evidence.service (unit file plus drop-ins), then
runs verification/role_sandbox_probe.py inside it as that identity via runuser,
exactly as the host does. Nothing is installed, restarted, sent or published.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

UNIT = "alfred-development-evidence.service"
PROBE = Path(__file__).with_name("role_sandbox_probe.py")
ROLES = ("alfred", "alfredqa", "alfredreview", "alfredpublish")
VIEW_MOUNT = "BindReadOnlyPaths=/home/alfred/Alfred/gateway:/run/alfred-fresh-v1-gateway"
# Root's own handoff step: snapshot the newest final worktree exactly as the Reviewer
# and Publisher preparation do (installed fresh_v1.host), into the private /tmp only.
ROOT_CLONE = r'''
import glob, json, os, pwd, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/usr/local/lib/alfred-fresh-v1")
from fresh_v1 import host
REPO = Path("/home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo")
finals = sorted(glob.glob("/var/lib/alfred-development-worktrees/fresh-*/*-final"),
                key=os.path.getmtime)
failures = []
if not hasattr(host, "clone_snapshot"):
    failures.append("installed host lacks clone_snapshot (handoff.7 not installed)")
elif not finals:
    failures.append("no final worktree available to clone")
else:
    for bare in (False, True):
        with tempfile.TemporaryDirectory() as tmp:
            try:
                host.clone_snapshot(Path(finals[-1]), Path(tmp) / "clone", REPO,
                                    pwd.getpwnam("alfred").pw_uid, bare=bare)
            except Exception as exc:
                failures.append(f"{'bare' if bare else 'snapshot'} clone of "
                                f"{Path(finals[-1]).name}: {type(exc).__name__} "
                                + repr(getattr(exc, "stderr", b"") or b"")[:160])
print(json.dumps({"user": "root (snapshot clone)", "checks": 2, "failures": failures}))
'''
# Only the settings that shape what a role can see, write, reach or execute.
SANDBOX = {
    "ProtectSystem", "ProtectHome", "PrivateTmp", "NoNewPrivileges", "ReadWritePaths",
    "BindReadOnlyPaths", "RestrictAddressFamilies", "CapabilityBoundingSet",
    "AmbientCapabilities", "SystemCallArchitectures", "UMask", "Group",
}


def properties(text):
    """Installed [Service] sandbox lines in file order, so resets apply as in systemd."""
    section, found = None, []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line
        elif section == "[Service]" and "=" in line and not line.startswith("#"):
            key = line.split("=", 1)[0]
            if key in SANDBOX:
                found.append(line)
    return found


def main():
    if os.geteuid() != 0:
        raise SystemExit("run as root: the preflight starts transient units")
    unit = subprocess.run(["/usr/bin/systemctl", "cat", UNIT], capture_output=True,
                          text=True, check=True).stdout
    props = properties(unit)
    if "--with-gateway-view" in sys.argv[1:]:
        # Preview handoff.5 before installing it: add only its read-only view mount.
        props.append(VIEW_MOUNT)
    if not any(p.startswith("BindReadOnlyPaths=") for p in props):
        print(json.dumps({"warning": "gateway view mount absent: handoff.5 not installed"}))
    probe = PROBE.read_bytes()
    results = []
    for user in (*ROLES, "root"):
        args = ["/usr/bin/systemd-run", "--quiet", "--wait", "--pipe", "--collect",
                "--service-type=exec", f"--unit=alfred-role-preflight-{user}"]
        for prop in props:
            args += ["-p", prop]
        if user == "root":
            args += ["/usr/bin/python3", "-I", "-B", "-"]
            stdin = ROOT_CLONE.encode()
        else:
            args += ["/usr/sbin/runuser", "-u", user, "--", "/usr/bin/python3", "-I", "-B", "-"]
            stdin = probe
        proc = subprocess.run(args, input=stdin, capture_output=True, timeout=180, check=False)
        line = proc.stdout.decode(errors="replace").strip().splitlines()[-1:] or [""]
        try:
            result = json.loads(line[0])
        except ValueError:
            result = {"user": user, "failures": [
                f"probe did not run (exit {proc.returncode}): "
                + proc.stderr.decode(errors="replace").strip()[:200]]}
        results.append(result)
        print(json.dumps(result))
    failed = [r["user"] for r in results if r.get("failures")]
    print(json.dumps({"overall": "FAIL" if failed else "PASS", "failed_roles": failed,
                      "sandbox_properties": len(props)}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
