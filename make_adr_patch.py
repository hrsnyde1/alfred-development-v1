"""Generate a review-only ADR 0003 unified diff inside this staging directory."""

from __future__ import annotations

import difflib
import hashlib
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = Path("/home/alfred/Git/alfred/docs/adr/0003-development-gateway.md")
PROPOSAL = HERE.parent / "proposals/ADR-0003-photon-gateway-front-amendment.md"
EXPECTED_SOURCE_SHA256 = "dbea1d82a79638e5e3fb2429dc2ba8bb684adb56aa7bf375434ee95e7d61d89a"
EXPECTED_PROPOSAL_SHA256 = "26704b183fe8778e22405b47eb170ae6a1fc1992bb2166fd4da0a2764c667002"


def main() -> None:
    old_bytes = SOURCE.read_bytes()
    proposal_bytes = PROPOSAL.read_bytes()
    if hashlib.sha256(old_bytes).hexdigest() != EXPECTED_SOURCE_SHA256:
        raise SystemExit("authoritative ADR changed; re-review before regenerating")
    if hashlib.sha256(proposal_bytes).hexdigest() != EXPECTED_PROPOSAL_SHA256:
        raise SystemExit("staging proposal changed; re-review before regenerating")
    old = old_bytes.decode("utf-8")
    body = proposal_bytes.decode("utf-8").split("## Context and current deployment\n", 1)[1]
    appendix = "\n## Proposed conditional Phase 4 Photon amendment — formal recording pending\n\n"
    appendix += "This appendix is a **proposed** amendment; conditional design approval and Task A staging work do not activate it.\n\n"
    appendix += "### Context and current deployment\n" + body
    new = old.rstrip("\n") + "\n" + appendix
    diff = "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                    fromfile="a/docs/adr/0003-development-gateway.md",
                                    tofile="b/docs/adr/0003-development-gateway.md"))
    target = HERE / "adr-0003-conditional-photon-front.proposed.patch"
    target.write_text(diff)


if __name__ == "__main__":
    main()
