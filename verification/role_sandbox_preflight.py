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
    for user in ROLES:
        args = ["/usr/bin/systemd-run", "--quiet", "--wait", "--pipe", "--collect",
                "--service-type=exec", f"--unit=alfred-role-preflight-{user}"]
        for prop in props:
            args += ["-p", prop]
        args += ["/usr/sbin/runuser", "-u", user, "--", "/usr/bin/python3", "-I", "-B", "-"]
        proc = subprocess.run(args, input=probe, capture_output=True, timeout=180, check=False)
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
