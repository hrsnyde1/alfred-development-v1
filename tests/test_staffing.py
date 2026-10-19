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
