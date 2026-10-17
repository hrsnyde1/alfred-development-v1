"""Read-only: would T-0009's recorded Reviewer result advance under the handoff.10 policy?

Run as root after `alfred-dev-ops install 10`, with PAUSE still set, from inside the
verified release:

    /usr/bin/python3 -I -B <release>/development_handoff10/verify_t0009.py

It evaluates the *installed* fresh_v1.handoffs.reviewer_blocker against the original
reviewer.result.json, prints every finding and condition, and proves the file's bytes
are unchanged. It writes nothing, sends nothing and starts no stage.
"""

import hashlib
import json
import sys
from pathlib import Path

INSTALLED = "/usr/local/lib/alfred-fresh-v1"
TASK = Path("/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0009")


def evaluate(task: Path, blocker) -> dict:
    path = task / "reviewer.result.json"
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    review = json.loads(path.read_bytes())
    coverage = review.get("acceptance_coverage") or []
    reason = blocker(review)
    after = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "reviewer_result_sha256": before,
        "reviewer_result_unchanged": before == after,
        "decision": review.get("decision"),
        "correctness": review.get("correctness"),
        "scope": review.get("scope"),
        "next_authorized_stage": review.get("next_authorized_stage"),
        "acceptance_criteria": [(row.get("criterion"), row.get("result")) for row in coverage
                                if isinstance(row, dict)],
        "findings": [(f.get("severity"), f.get("requirement"), f.get("detail"))
                     if isinstance(f, dict) else repr(f)
                     for f in (review.get("findings") or [])],
        "recorded_failures": sorted(p.name for p in task.glob("*.failure.json")),
        "publication_started": (task / "publication-plan.attempt.json").exists(),
        "verdict": "WILL_ADVANCE_TO_PUBLICATION_PREPARATION" if reason is None else "HELD",
        "held_reason": reason,
    }


def main() -> int:
    sys.path.insert(0, INSTALLED)
    from fresh_v1.handoffs import reviewer_blocker

    result = evaluate(TASK, reviewer_blocker)
    print(json.dumps(result, indent=2))
    ok = (result["reviewer_result_unchanged"] and not result["recorded_failures"]
          and not result["publication_started"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
