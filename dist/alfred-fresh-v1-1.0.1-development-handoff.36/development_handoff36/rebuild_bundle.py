"""Rebuild developer_v1/agent_profiles.json from an alfred-team-skills checkout.

    git -C <team-skills> archive <commit> agents | tar -x -C <dir>
    python3 development_handoff36/rebuild_bundle.py <dir>/agents <commit>

Deterministic: the same commit always gives the same bytes. Run on the bundle handoff.21
shipped (team-skills 59836a2), it reproduces that file exactly.
"""

import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
from developer_v1 import agent_profiles  # noqa: E402


def render(agents: Path, commit: str) -> bytes:
    bundle = agent_profiles.build(agents, commit)
    return (json.dumps(bundle, indent=1, sort_keys=True) + "\n").encode()


def main():
    agents, commit = Path(sys.argv[1]), sys.argv[2]
    raw = render(agents, commit)
    if len(raw) > agent_profiles.MAX_BUNDLE:
        raise SystemExit("bundle over MAX_BUNDLE")
    (LAB / "developer_v1" / "agent_profiles.json").write_bytes(raw)
    print(json.dumps({"commit": commit, "bytes": len(raw)}))


if __name__ == "__main__":
    main()
