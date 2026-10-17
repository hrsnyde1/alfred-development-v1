"""Read-only access probe: which QA inputs can the QA identity not open? Never writes.

Run as root, feeding this file on stdin so the QA user needs no access to the checkout:

    runuser -u alfredqa -- /usr/bin/python3 -I -B - T-0006 < verification/qa_access_probe.py

Walks every path the independent QA worker reads for one fresh V1 task and prints
only the paths it cannot stat, list or read (names and errno, never contents).
"""

import json
import os
import sys
from pathlib import Path

TASK = sys.argv[1]
PROJECT = "dev-v1-accept"
JOB = Path("/var/lib/alfred-v1-handoffs") / PROJECT / TASK
REPO = Path("/home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo")
TREES = Path("/var/lib/alfred-development-worktrees") / f"fresh-{PROJECT}-{TASK}"
denied, checked = [], 0


def probe(path):
    global checked
    checked += 1
    try:
        if path.is_symlink():
            return
        if path.is_dir():
            os.listdir(path)
        else:
            with open(path, "rb") as stream:
                stream.read(1)
    except OSError as exc:
        denied.append(f"{path}  errno={exc.errno}")


def walk(root):
    probe(root)
    for directory, dirs, files in os.walk(root, onerror=lambda e: denied.append(
            f"{e.filename}  errno={e.errno}")):
        for name in dirs + files:
            probe(Path(directory) / name)


for path in (JOB, JOB / "job.json", JOB / "worker-policy.json", JOB / "qa-output"):
    probe(path)
walk(JOB / "qa-input")
walk(JOB / "qa-output")
walk(REPO)
walk(TREES)
# fresh_v1/role.py checks these before every stage; Path.exists raises EACCES when
# the role identity cannot search the gateway directory (T-0006 QA failure).
for name in ("PAUSE", "STOP"):
    checked += 1
    try:
        (Path("/home/alfred/Alfred/gateway") / name).exists()
    except OSError as exc:
        denied.append(f"/home/alfred/Alfred/gateway/{name} (role pause check)  errno={exc.errno}")
for path in (
    Path("/opt/alfred-independent-qa-v1/independent_qa"),
    Path.home(),
    Path.home() / ".local/bin/codex",
    Path.home() / ".codex",
):
    probe(path)
print(json.dumps({"user": os.getuid(), "home": str(Path.home()), "checked": checked,
                  "denied": denied}, indent=2))
