"""handoff.12: one pipeline, several registered projects."""

import json
from pathlib import Path

import pytest
import yaml


from fresh_v1.host import project_view, projects, work_items
from tests.test_fresh_v1 import (DRAFT, HERMES, PROJECT, ROOT, SIDE, IntakeRefused, event,
                                 world)  # noqa: F401 (pytest fixture)

SHARED = {
    "enabled": True, "completion_state": "/c", "developer_state": "/d", "gateway_root": "/g",
    "gateway_state": "/s", "grant_root": "/gr", "intake_socket": "/i", "jobs": "/j",
    "models": "/m", "publisher_token": "/t", "registry": "/r", "total_cost_limit": 6,
    "worktree_root": "/w",
}
CALCULATOR = {"allowed_scope": ["calculator.py", "test_calculator.py"], "base_branch": "main",
              "destination": "hrsnyde1/alfred-dev-v1-acceptance", "repository": "/lab/calc",
              "specialists": ["backend"]}
DEMO = {"allowed_scope": ["app.js", "index.html", "styles.css", "tests/test_site.py"],
        "base_branch": "main", "destination": "hrsnyde1/alfred-demo-site",
        "repository": "/lab/demo", "specialists": ["frontend", "backend"]}


def v1():
    return {"schema": "alfred.fresh-v1-policy/1", **SHARED, **CALCULATOR,
            "project": "dev-v1-accept"}


def v2(**extra):
    return {"schema": "alfred.fresh-v1-policy/2", **SHARED,
            "projects": {"dev-v1-accept": CALCULATOR, "demo-site": DEMO, **extra}}


# --- Policy views ---------------------------------------------------------------------------

def test_existing_project_view_is_identical_to_the_old_policy():
    # Work frozen under the schema 1 policy (T-0010) keeps matching.
    assert project_view(v2(), "dev-v1-accept") == v1()
    assert project_view(v1(), "dev-v1-accept") == v1()


def test_each_project_gets_only_its_own_settings():
    view = project_view(v2(), "demo-site")
    assert view["project"] == "demo-site" and view["destination"] == DEMO["destination"]
    assert view["allowed_scope"] == DEMO["allowed_scope"] and "projects" not in view
    assert projects(v2()) == ["demo-site", "dev-v1-accept"]


@pytest.mark.parametrize("bad", [
    {"other": {**DEMO, "repository": "/lab/calc"}},                 # two projects, one repo
    {"Bad_Id": DEMO},
    {"x-site": {**DEMO, "specialists": ["security"]}},              # not staffable yet
    {"x-site": {**DEMO, "allowed_scope": ["../outside.py"]}},
    {"x-site": {**DEMO, "allowed_scope": []}},
    {"x-site": {k: v for k, v in DEMO.items() if k != "destination"}},
])
def test_invalid_project_policies_are_refused(bad):
    with pytest.raises(ValueError):
        projects(v2(**bad))


def test_unlisted_project_and_mixed_schemas_are_refused():
    with pytest.raises(ValueError):
        project_view(v2(), "unknown")
    with pytest.raises(ValueError):
        projects({**v2(), "destination": "x/y"})


# --- Staffing -------------------------------------------------------------------------------

def test_one_specialist_owns_every_file():
    [item] = work_items(DEMO["allowed_scope"], ["frontend"], "Add dark mode")
    assert item["id"] == "frontend-main" and item["files"] == DEMO["allowed_scope"]
    assert item["depends_on"] == []


def test_frontend_and_backend_split_files_without_overlap():
    scope = ["api/theme.py", "app.js", "index.html", "styles.css", "tests/test_theme.py"]
    backend, frontend = work_items(scope, ["frontend", "backend"], "Theme API and toggle")
    assert backend["files"] == ["api/theme.py", "tests/test_theme.py"]
    assert frontend["files"] == ["app.js", "index.html", "styles.css"]
    assert frontend["depends_on"] == ["backend-main"] and backend["depends_on"] == []


@pytest.mark.parametrize("specialists", [["frontend"], ["backend"], ["backend", "frontend"]])
def test_staffed_items_pass_the_developer_runners_own_checks(specialists):
    from developer_v1.execution import build_assignments

    scope = ["api/tip.py", "app.js", "index.html", "styles.css", "tests/test_site.py"]
    dispatch = {"project": "demo-site", "task_id": "T-0001", "scope": scope,
                "specialists": specialists}
    assignments = build_assignments(dispatch, work_items(scope, specialists, "Add dark mode"))
    assert sorted(f for a in assignments for f in a["files"]) == sorted(scope)


def test_a_specialist_without_files_cannot_be_staffed():
    with pytest.raises(ValueError):
        work_items(["styles.css"], ["frontend", "backend"], "x")
    with pytest.raises(ValueError):
        work_items(["a.py"], ["security"], "x")


# --- Recognising the project in plain language ----------------------------------------------

def with_demo_project(world):
    data = yaml.safe_load(Path(world.p["registry"]).read_bytes())
    demo = json.loads(json.dumps(data["projects"][0]))
    demo.update(id="demo-site", aliases=["harbor-and-pine"],
                local_path=str(world.root / "demo"))
    demo["repo"]["github"] = "fixtureowner/demo"
    data["projects"].append(demo)
    Path(world.p["registry"]).write_text(yaml.safe_dump(data))


@pytest.mark.parametrize("text,expected", [
    ("Alfred, add a light/dark mode to the demo site", "demo-site"),
    ("Add dark mode to Harbor and Pine please", "demo-site"),
    (f"Add a multiply helper in {PROJECT}", PROJECT),
])
def test_project_is_found_by_id_or_natural_alias(world, text, expected):
    with_demo_project(world)
    assert world.gate._project(text) == expected


@pytest.mark.parametrize("text", [
    "Add dark mode to the site",                       # names no project
    f"Add dark mode to the demo site and {PROJECT}",   # names two
    "Add dark mode to the demosite",                   # not an alias
])
def test_ambiguous_or_unnamed_projects_are_refused(world, text):
    with_demo_project(world)
    with pytest.raises(IntakeRefused):
        world.gate._project(text)


def test_a_task_waiting_on_the_owner_does_not_block_the_next_one(world):
    import os
    from unittest.mock import patch

    from fresh_v1 import host
    from fresh_v1.protected import protected_json
    from tests.test_fresh_v1 import OWNER, save

    world.submit()
    world.submit(identifier="mock-second-owner-request")
    save(world.gateway.gateway_dir / "v1-1-intake.json", {"owner_sender_id": OWNER})
    with (
        patch.object(host, "require_root"),
        patch.object(host, "root_directory", lambda path: None),
        patch.object(host, "protected_json", lambda p: protected_json(
            p, trusted_uid=os.geteuid(), trusted_root=world.root)),
        patch.object(host, "Host", return_value=world),
        patch.object(host.pwd, "getpwnam", return_value=type("Photon", (), {"pw_uid": SIDE})()),
    ):
        result = host.poll(world.policy_path)
        assert result["state"] == "awaiting_development_approval", result
    # Both tasks were planned in one tick; before, the second waited behind the first.
    assert world.calls == [("plan", "alfred"), ("plan", "alfred")]
    # The first approval text is still open, so the second never attempted its own
    # (an attempt refused by the intake would have held it as uncertain for good).
    jobs = sorted((Path(world.p["jobs"]) / PROJECT).iterdir())
    assert [(job / "development-challenge.attempt.json").exists() for job in jobs] == [True, False]
    assert len([m for m in world.messages if "Development execution approval" in m[1]]) == 1


def test_owner_registry_entry_for_the_demo_site_is_valid():
    from alfred.registry.loader import parse_registry

    template = yaml.safe_load((ROOT / "v1_1a/fixture/registry.template.yaml").read_bytes())
    entry = yaml.safe_load((ROOT / "development_handoff12/registry-demo-site.yaml").read_bytes())
    for project in template["projects"]:  # the template's placeholder path, as the world sets it
        if not project["local_path"].startswith(("/", "~/")):
            project["local_path"] = "/tmp/fixture-project"
    template["projects"].extend(entry)
    parsed = parse_registry(template)
    demo = parsed.project("demo-site")
    assert demo.repo.github == "hrsnyde1/alfred-demo-site"
    assert demo.permissions.hermes_requests and demo.status == "active"
    assert parsed.resolve("demo-site").outcome == "resolved"
