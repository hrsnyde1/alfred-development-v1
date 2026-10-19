"""Who each development agent is: the owner-reviewed identity files, as prompt text.

The profiles come from the alfred-team-skills repository (`agents/<id>/`) at one
commit and ship inside this pinned release as `agent_profiles.json`, so an agent's
identity changes only through a reviewed release. `build` regenerates the bundle
from a checkout of that repository.

A profile shapes how an agent works. It never widens what it may touch: files,
commands and scope still come from the owner-approved plan.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

from .router import Denied

BUNDLE = Path(__file__).with_name("agent_profiles.json")
SCHEMA = "alfred.agent-profiles/1"
# Prompt order: who the agent is first, then how it works, then how it hands off.
FILES = ("Soul.md", "Role.md", "Skills.md", "Tools.md", "Workflow.md", "Quality.md",
         "Handoff.md", "Memory.md")
# Read when an agent has it (the CTO first, 2026-10-19); appended after FILES.
OPTIONAL = ("Escalation.md",)
FIELDS = {"schema", "id", "name", "provider", "model", "effort", "style", "squads"}
AGENT_ID = re.compile(r"^[a-z][a-z_]{1,31}$")
MAX_PROFILE = 12288
MAX_BUNDLE = 262144


def _bundle(path: Path | None) -> dict:
    """The bundle, only when it is as protected as the code that reads it."""
    path = path or BUNDLE
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {}
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or info.st_uid != os.stat(__file__).st_uid or info.st_mode & 0o022
                or info.st_size > MAX_BUNDLE):
            raise Denied("agent profiles are not protected")
        raw = os.read(fd, MAX_BUNDLE + 1)
    finally:
        os.close(fd)
    data = json.loads(raw)
    if type(data) is not dict or data.get("schema") != SCHEMA or type(data.get("agents")) is not dict:
        raise Denied("agent profiles bundle invalid")
    return data


def identity(agent: str, path: Path | None = None) -> str:
    """The identity prompt for one agent; empty when the release carries no profile."""
    profile = _bundle(path).get("agents", {}).get(agent)
    if profile is None:
        return ""
    text = profile.get("text")
    if type(text) is not str or not text or len(text.encode()) > MAX_PROFILE:
        raise Denied("agent profile invalid: " + agent)
    return text


def card(agent: str, path: Path | None = None) -> dict | None:
    """The agent's agent.json (model, effort, style, squads), or None."""
    profile = _bundle(path).get("agents", {}).get(agent)
    return None if profile is None else profile["card"]


def build(agents_dir: Path, commit: str) -> dict:
    """Bundle `agents/` from an alfred-team-skills checkout at `commit`."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be a full SHA-1")
    agents = {}
    for folder in sorted(p for p in agents_dir.iterdir() if p.is_dir()):
        meta = json.loads((folder / "agent.json").read_text())
        if set(meta) != FIELDS or meta["schema"] != "alfred.agent/1" or meta["id"] != folder.name:
            raise ValueError("bad agent.json: " + folder.name)
        if not AGENT_ID.match(meta["id"]):
            raise ValueError("bad agent id: " + folder.name)
        names = FILES + tuple(n for n in OPTIONAL if (folder / n).is_file())
        text = "\n\n".join((folder / name).read_text().strip() for name in names)
        if len(text.encode()) > MAX_PROFILE:
            raise ValueError("profile too large: " + folder.name)
        agents[meta["id"]] = {"card": meta, "text": text}
    squads = json.loads((agents_dir / "squads.json").read_text())
    return {"schema": SCHEMA, "source": {"repository": "hrsnyde1/alfred-team-skills",
                                         "commit": commit}, "squads": squads["squads"],
            "agents": agents}


if __name__ == "__main__":
    # python3 -m developer_v1.agent_profiles <team-skills>/agents <commit>
    bundle = build(Path(sys.argv[1]), sys.argv[2])
    BUNDLE.write_text(json.dumps(bundle, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"{len(bundle['agents'])} profiles from {sys.argv[2][:12]}")
