"""Read-only verifier for a live T-0002 Independent QA report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .host_preflight import DEVELOPER, EVIDENCE, FINAL, QA_INPUT, REPOSITORY, verify_handoff
from .worker import changed_paths, digest, git

BASELINE = "9000574c4c8807e84c4350e2fd342deeba341d7d"
DEVELOPER_COMMIT = "867fde90acf3f0055af79bda53a0fccb55f6bf34"
FINAL_REVISION = "89ba188f8a2f801d433a30c9c21363efb3e1043d"
FILE_SHA256 = "8b7592a111b9a05664ec660fb67d926fa3810ff816dd5fb50ea37eae72284c5b"
QA_INPUT_SHA256 = "62b2657cb31747b368c0c066107a4afa42ea21350e82563a9b67ed16964a0171"
DEVELOPER_REPORT_SHA256 = "81f924168f3452b3507650ce4f58ace315dbff7fb33de14d42b97550e2cdeb6d"


def inspect(install_root: Path, output_root: Path, evidence_root: Path | None = EVIDENCE) -> dict:
    if evidence_root is not None:
        verify_handoff(evidence_root)
    package = install_root / "independent_qa"
    result_dir = output_root / "dev-v1-accept" / "T-0002"
    report_bytes = (result_dir / "qa-report.json").read_bytes()
    report = json.loads(report_bytes)
    if evidence_root is not None:
        assert report["evidence"]["qa_input_path"] == str(evidence_root / "dev-v1-accept/T-0002/qa-input.json")
        assert report["evidence"]["developer_reports"]["backend-subtract"]["path"] == str(
            evidence_root / "dev-v1-accept/T-0002/report-backend-subtract.json")
    handoff = json.loads((result_dir / "reviewer-handoff.json").read_bytes())
    Draft202012Validator(json.loads((package / "schemas/qa-report.schema.json").read_text())).validate(report)
    Draft202012Validator(json.loads((package / "schemas/reviewer-handoff.schema.json").read_text())).validate(handoff)
    assert report["decision"] == "PASS"
    assert report["project"] == handoff["project"] == "dev-v1-accept"
    assert report["task_id"] == handoff["task_id"] == "T-0002"
    assert report["baseline_revision"] == handoff["baseline_revision"] == BASELINE
    assert report["developer_commits"] == handoff["developer_commits"] == [DEVELOPER_COMMIT]
    assert report["final_revision"] == handoff["final_revision"] == FINAL_REVISION
    assert report["changed_file_hashes"] == handoff["changed_file_hashes"] == {"calculator.py": FILE_SHA256}
    assert handoff["qa_report_sha256"] == digest(report_bytes)
    assert handoff["next_stage"] == "independent_reviewer"
    assert len(report["tests"]) == 2
    assert {row["id"] for row in report["tests"]} == {"calculator_examples", "python_unittest"}
    assert all(row["result"] == "PASS" and row["exit_code"] == 0 for row in report["tests"])
    assert "add=10 subtract=4" in next(row["output"] for row in report["tests"] if row["id"] == "calculator_examples")
    assert "Ran 2 tests" in next(row["output"] for row in report["tests"] if row["id"] == "python_unittest")
    assert len(report["acceptance_criteria"]) == 3 and all(row["result"] == "PASS" for row in report["acceptance_criteria"])
    assert report["evidence"]["qa_input_sha256"] == QA_INPUT_SHA256
    assert report["evidence"]["development_grant_reference"] == "445759a699d9423bbb5a8f1dd589689a"
    assert report["evidence"]["developer_reports"]["backend-subtract"]["sha256"] == DEVELOPER_REPORT_SHA256
    assert digest(QA_INPUT.read_bytes()) == QA_INPUT_SHA256
    assert digest(QA_INPUT.with_name("report-backend-subtract.json").read_bytes()) == DEVELOPER_REPORT_SHA256
    assert digest((FINAL / "calculator.py").read_bytes()) == FILE_SHA256
    assert git(REPOSITORY, "rev-parse", "HEAD") == BASELINE
    assert git(DEVELOPER, "rev-parse", "HEAD") == DEVELOPER_COMMIT
    assert git(FINAL, "rev-parse", "HEAD") == FINAL_REVISION
    assert changed_paths(FINAL, BASELINE, FINAL_REVISION) == ["calculator.py"]
    assert git(REPOSITORY, "status", "--porcelain", "--untracked-files=all") == \
           "?? .dev/tasks/T-0002-backend-calculator-subtract-helper.md"
    assert all(not git(repo, "status", "--porcelain", "--untracked-files=all") for repo in (DEVELOPER, FINAL))
    return {"result": "PASS", "project": "dev-v1-accept", "task_id": "T-0002",
            "developer_commit": DEVELOPER_COMMIT, "final_revision": FINAL_REVISION,
            "qa_report_sha256": digest(report_bytes), "next_stage": "independent_reviewer"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-root", type=Path, default=Path("/opt/alfred-independent-qa-v1"))
    parser.add_argument("--output-root", type=Path, default=Path("/var/lib/alfred-independent-qa-state"))
    args = parser.parse_args()
    print(json.dumps(inspect(args.install_root, args.output_root), sort_keys=True))


if __name__ == "__main__":
    main()
