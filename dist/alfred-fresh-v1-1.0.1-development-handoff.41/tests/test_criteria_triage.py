"""handoff.41: only code-checkable criteria go on the QA and Review checklist."""

from fresh_v1.role import triage_criteria

# demo-site T-0013's criteria exactly as filed (2026-10-20). The Reviewer found "no
# concrete code defect" but held the task on the last three after three fix rounds.
T0013 = """- [ ] In-page anchor links scroll smoothly via CSS scroll-behavior (or equivalent), without any JS override of normal mouse-wheel or trackpad scrolling
- [ ] Normal page scrolling (wheel/trackpad/keyboard) behaves exactly as before — no custom scroll hijacking, momentum changes, or scroll-speed alteration
- [ ] Smooth-scroll behavior respects prefers-reduced-motion (falls back to instant jump)
- [ ] All primary interactive elements (nav links, buttons, cards, images) have clear, consistent hover states
- [ ] On-scroll reveal/fade-in transitions are applied to section content and respect prefers-reduced-motion
- [ ] No existing content, copy, layout structure, or functionality is changed or broken
- [ ] Site is verified responsive and functional on desktop and mobile after changes
- [ ] Changes pass Build -> QA -> Review cycle with no merge/deploy until Hayden explicitly approves"""

# dev-v1-accept T-0010's criteria (the calculator), which already passed review.
CALCULATOR = """- [ ] cube(a) implemented and returns a * a * a.
- [ ] add, subtract, multiply, power, square, negate, absolute preserved and unchanged.
- [ ] unittest coverage added for cube (positive, negative, zero).
- [ ] existing tests still pass.
- [ ] only calculator.py and test_calculator.py modified.
- [ ] no merge or deployment performed."""


def plan(criteria):
    return {"acceptance_criteria": criteria, "risks_blockers": ["Existing risk."]}


def checklist(p):
    return [l[6:] for l in p["acceptance_criteria"].splitlines() if l.startswith("- [ ] ")]


def test_t0013_keeps_the_five_code_checkable_criteria():
    p = plan(T0013)
    triage_criteria(p)
    assert [c[:30] for c in checklist(p)] == [
        "In-page anchor links scroll sm", "Normal page scrolling (wheel/t",
        "Smooth-scroll behavior respect", "All primary interactive elemen",
        "On-scroll reveal/fade-in trans"]
    assert p["risks_blockers"][0] == "Existing risk."
    assert p["risks_blockers"][1].startswith("Enforced by the pipeline, not checked in code: Changes pass Build")
    assert [r.split(": ", 1)[1][:20] for r in p["risks_blockers"][2:]] == [
        "No existing content,", "Site is verified res"]
    assert all(r.startswith("Hayden checks on the draft PR") for r in p["risks_blockers"][2:])


def test_the_calculator_keeps_every_code_criterion_and_moves_only_the_process_one():
    p = plan(CALCULATOR)
    triage_criteria(p)
    assert len(checklist(p)) == 5 and "no merge or deployment performed." not in checklist(p)
    assert p["risks_blockers"][1] == ("Enforced by the pipeline, not checked in code: "
                                      "no merge or deployment performed.")


def test_criteria_that_are_all_code_checkable_are_untouched():
    p = plan("- [ ] cube(a) returns a * a * a.\n- [ ] tests cover zero.")
    before = dict(p)
    triage_criteria(p)
    assert p == before


def test_nothing_checkable_left_means_no_change():
    p = plan("- [ ] Looks right on desktop and mobile.\n- [ ] Hayden signs off.")
    triage_criteria(p)
    assert p["acceptance_criteria"].startswith("- [ ] Looks right") and len(p["risks_blockers"]) == 1


def test_qa_and_the_reviewer_read_the_same_checklist_after_triage():
    # QA counts every non-empty line; the Reviewer counts only "- [ ] " lines.
    p = plan(T0013)
    triage_criteria(p)
    lines = [l for l in p["acceptance_criteria"].splitlines() if l.strip()]
    assert len(lines) == len(checklist(p)) == 5
