"""handoff.10: an APPROVED Reviewer result may advance to draft PR preparation when its
findings are empty or exclusively informational. Nothing else is relaxed."""

import copy
import json

import jsonschema
import pytest

from developer_v1 import publication_approval
from draft_pr_publisher import worker as publisher
from fresh_v1.handoffs import reviewer_blocker
from tests.test_fresh_v1 import ROOT
from tests.test_fresh_v1 import world  # noqa: F401 (pytest fixture)

INFO = {"severity": "info", "requirement": "maintainability",
        "detail": "absolute() could share a docstring style with add()", "evidence": "calculator.py"}
WARNING = {**INFO, "severity": "warning", "detail": "edge case not documented"}
APPROVED = {
    "schema": "alfred.review-report/1", "decision": "APPROVED", "correctness": "PASS",
    "scope": "PASS", "next_authorized_stage": "github_draft_pr_preparation",
    "acceptance_coverage": [{"criterion": "cube(a) returns a**3", "result": "PASS",
                             "evidence": "unittest"}],
    "findings": [],
}


def review(**changes):
    value = copy.deepcopy(APPROVED)
    value.update(changes)
    return value


# --- The Fresh V1 gate --------------------------------------------------------------------

@pytest.mark.parametrize("findings", [[], [INFO], [INFO, {**INFO, "requirement": "style"}]])
def test_approved_with_no_or_only_info_findings_advances(findings):
    assert reviewer_blocker(review(findings=findings)) is None


@pytest.mark.parametrize("finding", [
    WARNING,
    {**INFO, "severity": "error"},
    {**INFO, "severity": "critical"},
    {**INFO, "severity": "high"},
    {**INFO, "severity": "INFO"},
    {**INFO, "severity": "unknown"},
    {key: value for key, value in INFO.items() if key != "severity"},
    {**INFO, "severity": None},
    {**INFO, "detail": ""},
    {**INFO, "evidence": 3},
    "info",
    None,
])
def test_any_non_info_missing_or_malformed_finding_blocks(finding):
    assert reviewer_blocker(review(findings=[finding])) == \
        "independent Reviewer findings require resolution"


def test_mixed_info_and_warning_blocks():
    assert reviewer_blocker(review(findings=[INFO, WARNING])) is not None


@pytest.mark.parametrize("findings", [None, {}, "info", ({**INFO},)])
def test_findings_that_are_not_a_list_block(findings):
    assert reviewer_blocker(review(findings=findings)) is not None


@pytest.mark.parametrize("changes", [
    {"decision": "CHANGES_REQUESTED"},
    {"decision": "BLOCKED"},
    {"decision": None},
    {"correctness": "CHANGES_REQUESTED"},
    {"scope": "BLOCKED"},
    {"next_authorized_stage": "developer_correction_request"},
    {"acceptance_coverage": []},
    {"acceptance_coverage": None},
    {"acceptance_coverage": [{"criterion": "x", "result": "FAIL", "evidence": "e"}]},
    {"acceptance_coverage": [{"criterion": "x", "result": "PASS", "evidence": "e"},
                             {"criterion": "y", "result": "BLOCKED", "evidence": "e"}]},
])
def test_info_findings_never_override_another_blocking_condition(changes):
    assert reviewer_blocker(review(findings=[INFO], **changes)) is not None


def test_non_dict_result_blocks():
    assert reviewer_blocker(None) is not None
    assert reviewer_blocker([]) is not None


# --- The Publisher seals the notes and independently refuses anything else --------------

@pytest.mark.parametrize("findings", [[], [INFO]])
def test_publisher_passes_info_findings_through_for_sealing(findings):
    assert publisher.informational_findings({"findings": findings}) == findings


@pytest.mark.parametrize("findings", [
    [WARNING], [INFO, WARNING], [{**INFO, "severity": "critical"}],
    [{**INFO, "extra": "x"}], [{**INFO, "detail": ""}], ["info"], None, {},
])
def test_publisher_independently_refuses_non_info_findings(findings):
    with pytest.raises(publisher.PublicationError):
        publisher.informational_findings({"findings": findings})


def test_plan_schema_refuses_non_info_findings():
    schema = json.loads((ROOT / "developer_v1/schemas/publication-plan.schema.json").read_text())
    findings = schema["properties"]["review_findings"]
    jsonschema.validate([INFO], findings)
    for bad in ([WARNING], [{**INFO, "extra": "x"}], [{**INFO, "detail": ""}]):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, findings)


# --- The owner's publication approval text -----------------------------------------------

def test_approval_text_without_notes_is_unchanged():
    reference = "a" * 32
    text = publication_approval._challenge_text(reference)
    assert "Reviewer notes" not in text
    assert text == publication_approval._challenge_text(reference, notes=())


def test_approval_text_lists_every_note_within_bounds():
    notes = publication_approval._notes({"review_findings": [INFO]})
    text = publication_approval._challenge_text("a" * 32, notes=notes)
    assert "Reviewer notes (informational, non-blocking):" in text
    assert f"- {INFO['requirement']}: {INFO['detail']}" in text
    many = tuple((f"r{i}", "x" * 300) for i in range(20))
    bounded = publication_approval._notes_text(many)
    assert len(bounded) < publication_approval.NOTES_TOTAL + 400
    assert "more in the sealed publication plan" in bounded


# --- End to end through the real Reviewer, Publisher and owner approval ------------------

def test_info_finding_reaches_owner_approval_and_draft_pr(world):
    world.review_findings = [INFO]
    world.submit()
    assert world.tick() == {"state": "awaiting_development_approval"}
    world.approve_development()
    assert world.tick() == {"state": "awaiting_publication_approval"}
    plan = json.loads((world.jobdir(world.job) / "publication/approved-plan.json").read_bytes())
    assert plan["review_findings"] == [INFO]
    assert INFO["detail"] in world.messages[-1][1]
    assert "Reviewer notes (informational, non-blocking)" in world.messages[-1][1]
    world.approve_publication()
    result = world.tick()
    assert result["state"] == "complete", result
    assert len(world.pushes) == 1


def test_mixed_info_and_warning_stops_before_publication(world):
    world.review_findings = [INFO, WARNING]
    world.submit()
    world.tick()
    world.approve_development()
    result = world.tick()
    assert result["state"] == "held"
    assert not world.pushes
    assert not (world.jobdir(world.job) / "publication-plan.attempt.json").exists()
    assert not any("GitHub Draft PR publication approval" in m[1] for m in world.messages)


# --- The read-only T-0009 verification shipped with handoff.10 -----------------------------

def test_t0009_verifier_reports_without_changing_the_reviewer_result(tmp_path):
    from development_handoff10 import verify_t0009

    task = tmp_path / "T-0009"
    task.mkdir()
    raw = json.dumps(review(findings=[INFO]), sort_keys=True).encode()
    (task / "reviewer.result.json").write_bytes(raw)
    result = verify_t0009.evaluate(task, reviewer_blocker)
    assert result["verdict"] == "WILL_ADVANCE_TO_PUBLICATION_PREPARATION"
    assert result["reviewer_result_unchanged"] and not result["publication_started"]
    assert result["findings"] == [("info", INFO["requirement"], INFO["detail"])]
    assert (task / "reviewer.result.json").read_bytes() == raw
    assert sorted(p.name for p in task.iterdir()) == ["reviewer.result.json"]

    (task / "reviewer.result.json").write_bytes(
        json.dumps(review(findings=[INFO, WARNING])).encode())
    assert verify_t0009.evaluate(task, reviewer_blocker)["verdict"] == "HELD"
