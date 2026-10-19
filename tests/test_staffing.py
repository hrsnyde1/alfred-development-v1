"""handoff.37: plain-language requests are staffed from the files the work touches."""

import pytest

from fresh_v1.role import by_files, staff

DEMO_SITE = ["api/tip.py", "app.js", "index.html", "styles.css",
             "tests/test_site.py", "tests/test_tip_api.py"]


def plan(scope="", expected=(), files=DEMO_SITE):
    return {"scope": scope, "expected_components_files": list(expected),
            "repository_evidence": {"files": list(files)}}


def spec(title, objective=""):
    return {"title": title, "sections": {"objective": objective}}


def test_hayden_s_t_0008_request_goes_to_frontend_without_saying_frontend():
    # The exact canonical title of demo-site T-0008 (2026-10-19). Keyword routing
    # chose Builder (from "Alfred"), which demo-site does not staff; planning held.
    request = spec("Harbor & Pine Studio demo site: UI/UX polish (scroll, hover, "
                   "micro-interactions)", "Alfred-demo-site: clean scrolling and hover states")
    specialists, files, listed = staff(
        request, plan(expected=["app.js", "index.html", "styles.css"]), DEMO_SITE,
        ["backend", "frontend"])
    assert specialists == ["frontend"]
    assert files == ["app.js", "index.html", "styles.css"] and listed


def test_a_plain_request_touching_server_and_page_staffs_both_in_order():
    request = spec("Show a tip of the day on the home page", "Serve a tip and show it")
    specialists, files, _ = staff(
        request, plan(expected=["api/tip.py", "app.js", "index.html"]), DEMO_SITE,
        ["backend", "frontend"])
    assert specialists == ["backend", "frontend"]
    assert files == ["api/tip.py", "app.js", "index.html"]


def test_a_backend_only_project_keeps_its_one_developer():
    present = ["calculator.py", "test_calculator.py"]
    request = spec("Add modulo to the calculator", "modulo(a, b) returns a % b")
    specialists, files, _ = staff(
        request, plan(scope="calculator.py and test_calculator.py", files=present),
        present, ["backend"])
    assert specialists == ["backend"] and files == present


def test_keyword_routing_that_the_project_allows_is_unchanged():
    request = spec("Add dark mode to the website", "theme toggle")
    specialists, files, listed = staff(
        request, plan(expected=["app.js", "styles.css"]), DEMO_SITE, ["backend", "frontend"])
    assert specialists == ["frontend"] and files == ["app.js", "styles.css"] and listed


def test_a_builder_only_project_gets_builder_for_any_files():
    assert by_files(["app.js", "api/tip.py"], ["builder"]) == ["builder"]


def test_named_files_decide_and_are_not_relisted():
    request = spec("Tidy up the footer", "Only styles.css")
    specialists, files, listed = staff(
        request, plan(scope="Change styles.css only"), DEMO_SITE, ["backend", "frontend"])
    assert specialists == ["frontend"] and files == ["styles.css"] and not listed


def test_nothing_the_project_staffs_means_clarification():
    specialists, files, _ = staff(spec("Tidy the docs", "README"),
                                  plan(expected=["README.md"], files=["README.md"]),
                                  ["README.md"], ["frontend"])
    assert files == []


@pytest.mark.parametrize("files,allowed,expected", [
    (["styles.css"], ["backend", "frontend"], ["frontend"]),
    (["api/tip.py"], ["backend", "frontend"], ["backend"]),
    (["api/tip.py", "app.js"], ["frontend"], []),
    ([], ["backend"], []),
])
def test_by_files(files, allowed, expected):
    assert by_files(files, allowed) == expected


# --- handoff.39: one staffing record, read by every later step ------------------------

from developer_v1.router import Denied, select_specialists  # noqa: E402

T0008 = spec("Harbor & Pine Studio demo site: UI/UX polish (scroll, hover, "
             "micro-interactions)", "Alfred-demo-site: clean scrolling and hover states")


def test_the_plan_s_record_is_what_approval_and_dispatch_route_by():
    # demo-site T-0009 (2026-10-19): the plan step chose Frontend, but intake's approval
    # request and the developer dispatch guessed Builder again from keywords, so the
    # developer step refused the approved Frontend work item.
    assert select_specialists(T0008, plan()) == ["builder"]
    assert select_specialists(T0008, {**plan(), "specialists": ["frontend"]}) == ["frontend"]


def test_the_plan_step_ignores_an_earlier_record_and_decides_afresh():
    stale = {**plan(expected=["app.js", "index.html", "styles.css"]), "specialists": ["backend"]}
    specialists, files, _ = staff(T0008, stale, DEMO_SITE, ["backend", "frontend"])
    assert specialists == ["frontend"] and files == ["app.js", "index.html", "styles.css"]


@pytest.mark.parametrize("record", [[], ["frontend", "frontend"], ["wizard"], "frontend", [1]])
def test_an_invalid_record_is_refused(record):
    with pytest.raises(Denied):
        select_specialists(T0008, {**plan(), "specialists": record})


def test_the_schema_accepts_the_record_and_nothing_else_new():
    import json
    from pathlib import Path
    schema = json.loads((Path(__file__).resolve().parents[1] / "v1_cto/plan.schema.json").read_text())
    assert schema["additionalProperties"] is False
    assert schema["properties"]["specialists"]["minItems"] == 1
