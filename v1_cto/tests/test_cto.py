import copy
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from v1_cto import bind_delivery, cto

REQUEST = "11111111-2222-4333-8444-555555555555"
SPEC = f"""---
id: T-0002
title: Add dark mode to sample website
status: proposed
source: hermes
risk: null
company: alfred
created: '2026-10-15'
approved_by: null
branch: null
pr: null
project: dev-001
request_id: {REQUEST}
---

## Objective
Add dark mode to the sample website.

## Scope
Frontend theme toggle and persistence.

## Requirements
Add a toggle, persist choice, and follow OS preference when unset.

## Constraints
No backend changes or new dependencies.

## Acceptance criteria
- [ ] Toggle works on every page.
- [ ] Choice survives reload.

## Security considerations
Do not store sensitive data.

## Testing requirements
Check persistence and OS default.

## Implementation notes


## Log
- received from hermes; proposed
"""


def setup_case(tmp_path, *, site=True, spec=True, valid_outcome=True):
    repo = tmp_path / "repo"
    tasks = repo / ".dev" / "tasks"
    tasks.mkdir(parents=True)
    (repo / "README.md").write_text("Synthetic website fixture.\n")
    if site:
        (repo / "index.html").write_text(
            "<html><body><button>Example</button></body></html>\n"
        )
        (repo / "style.css").write_text("body { background: white; color: black; }\n")
        (repo / "test_theme.py").write_text("def test_placeholder(): assert True\n")
    if spec:
        (tasks / "T-0002-add-dark-mode.md").write_text(SPEC)
    registry = copy.deepcopy(
        cto.read_registry_data(Path("/home/alfred/Git/alfred/registry/projects.yaml"))
    )
    for project in registry["projects"]:
        if project["id"] == "dev-001":
            project["local_path"] = str(repo)
        elif project["id"] == "alfred":
            project["local_path"] = str(tmp_path / "forbidden")
    registry_path = tmp_path / "registry.yaml"
    registry_path.write_text(yaml.safe_dump(registry))
    gateway = tmp_path / "gateway"
    gateway.mkdir()
    row = {
        "kind": "outcome",
        "outcome": "filed",
        "project": "dev-001",
        "task_id": "T-0002" if valid_outcome else "bad",
        "request_id": REQUEST,
        "revision": 1,
        "file": "synthetic.json",
        "reason": "",
    }
    (gateway / "journal.jsonl").write_text(json.dumps(row) + "\n")
    config = tmp_path / "delivery.json"
    config.write_text(
        json.dumps(
            {
                "owner_space_id": "trusted-owner-dm",
                "sidecar_port": 8789,
                "sidecar_token": "synthetic-token",
            }
        )
    )
    return repo, gateway, registry_path, config


def run_case(gateway, registry, config, sender):
    return cto.poll(
        gateway_dir=gateway, registry_path=registry, config_path=config, sender=sender
    )


def test_filed_task_planned_once_and_one_owner_request(tmp_path):
    repo, gateway, registry, config = setup_case(tmp_path)
    sends = []

    def sender(cfg, message):
        sends.append((cfg, message))
        return "outbound-1"

    before = {
        p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in repo.rglob("*")
        if p.is_file()
    }
    assert run_case(gateway, registry, config, sender) == {
        "planned": 1,
        "delivered": 1,
        "existing": 0,
        "unavailable": 0,
    }
    assert run_case(gateway, registry, config, sender) == {
        "planned": 0,
        "delivered": 0,
        "existing": 1,
        "unavailable": 0,
    }
    assert len(sends) == 1
    assert "Here's how we'll build it. Do you approve development?" in sends[0][1]
    assert {
        p.relative_to(repo).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in repo.rglob("*")
        if p.is_file()
    } == before
    plan = json.loads((gateway / "cto-plans/dev-001-T-0002.json").read_text())
    assert plan["schema"] == "alfred.cto-plan/1"
    assert plan["approval_state"] == "awaiting_development_approval"
    assert plan["delivery"] == {"state": "delivered", "message_id": "outbound-1"}
    assert plan["expected_components_files"] == ["index.html", "style.css"]
    assert "test_theme.py" in plan["repository_evidence"]["test_files"]
    assert (
        plan["developer_work_items"]
        and plan["qa_checklist"]
        and plan["independent_review_criteria"]
    )
    assert plan["planning_note"].endswith("no development is authorized.")


def test_only_bound_project_is_read(tmp_path, monkeypatch):
    repo, gateway, registry, config = setup_case(tmp_path)
    forbidden = tmp_path / "forbidden"
    forbidden.mkdir()
    (forbidden / "secret.txt").write_text("do not read")
    seen = []
    real_read = cto._regular_bytes

    def watch(path, limit):
        seen.append(path)
        assert not path.is_relative_to(forbidden)
        return real_read(path, limit)

    monkeypatch.setattr(cto, "_regular_bytes", watch)
    assert run_case(gateway, registry, config, lambda *_: "sent")["planned"] == 1
    assert any(path.is_relative_to(repo) for path in seen)


@pytest.mark.parametrize("options", [{"spec": False}, {"valid_outcome": False}])
def test_invalid_or_missing_records_fail_closed(tmp_path, options):
    _, gateway, registry, config = setup_case(tmp_path, **options)
    sends = []
    result = run_case(gateway, registry, config, lambda *_: sends.append(1))
    assert result["unavailable"] == 1
    assert not sends
    assert not (gateway / "cto-plans").exists()


def test_spec_request_mismatch_and_gateway_pause_fail_closed(tmp_path):
    repo, gateway, registry, config = setup_case(tmp_path)
    (gateway / "PAUSE").write_text("")
    assert run_case(gateway, registry, config, lambda *_: "sent")["planned"] == 0
    assert not (gateway / "cto-plans").exists()
    (gateway / "PAUSE").unlink()
    spec = repo / ".dev/tasks/T-0002-add-dark-mode.md"
    spec.write_text(SPEC.replace(REQUEST, "99999999-2222-4333-8444-555555555555"))
    calls = []
    assert (
        run_case(gateway, registry, config, lambda *_: calls.append(1))["unavailable"]
        == 1
    )
    assert not calls
    assert not (gateway / "cto-plans").exists()


def test_no_website_requires_clarification_and_keeps_approval_pending(tmp_path):
    _, gateway, registry, config = setup_case(tmp_path, site=False)
    assert run_case(gateway, registry, config, lambda *_: "sent")["planned"] == 1
    plan = json.loads((gateway / "cto-plans/dev-001-T-0002.json").read_text())
    assert plan["clarification_required"] is True
    assert plan["clarification_questions"]
    assert plan["approval_state"] == "awaiting_development_approval"
    assert plan["expected_components_files"] == []


def test_delivery_failure_preserves_plan_without_automatic_retry(tmp_path):
    _, gateway, registry, config = setup_case(tmp_path)
    sends = []

    def fail(*_):
        sends.append(1)
        raise TimeoutError("uncertain")

    assert run_case(gateway, registry, config, fail)["planned"] == 1
    assert run_case(gateway, registry, config, fail)["existing"] == 1
    assert sends == [1]
    plan = json.loads((gateway / "cto-plans/dev-001-T-0002.json").read_text())
    assert plan["delivery"]["state"] == "attempted_uncertain"
    assert plan["approval_state"] == "awaiting_development_approval"


def test_tampered_approval_state_is_rejected_and_cannot_send(tmp_path):
    _, gateway, registry, config = setup_case(tmp_path)
    assert run_case(gateway, registry, config, lambda *_: "sent")["planned"] == 1
    path = gateway / "cto-plans/dev-001-T-0002.json"
    plan = json.loads(path.read_text())
    plan["approval_state"] = "development_approved"
    path.write_text(json.dumps(plan))
    with pytest.raises(cto.CTOError):
        cto.show_plan(gateway, "dev-001", "T-0002")
    calls = []
    assert (
        run_case(gateway, registry, config, lambda *_: calls.append(1))["unavailable"]
        == 1
    )
    assert not calls


def test_gateway_cli_exposes_full_plan_from_staged_patch(tmp_path):
    _, gateway, registry, config = setup_case(tmp_path)
    run_case(gateway, registry, config, lambda *_: "sent")
    checkout = tmp_path / "checkout"
    binary = checkout / ".dev/bin"
    binary.mkdir(parents=True)
    source = Path("/home/alfred/Git/alfred/.dev/bin/gateway.py")
    shutil.copy2(source, binary / "gateway.py")
    shutil.copy2(Path(cto.__file__), binary / "cto.py")
    shutil.copy2(
        Path(cto.__file__).with_name("plan.schema.json"), binary / "plan.schema.json"
    )
    patch = Path(__file__).resolve().parents[1] / "gateway-cto-plan.proposed.patch"
    if '"cto-plan"' in (binary / "gateway.py").read_text():
        reversed_patch = subprocess.run(
            ["patch", "-R", "-p1", "-i", str(patch)],
            cwd=checkout,
            capture_output=True,
            text=True,
            check=False,
        )
        assert reversed_patch.returncode == 0, reversed_patch.stderr
    applied = subprocess.run(
        ["patch", "-p1", "-i", str(patch)],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    assert applied.returncode == 0, applied.stderr
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        f"{binary}:/home/alfred/Git/alfred/.dev/bin:/home/alfred/Git/alfred/src"
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [
            "/home/alfred/Git/alfred/.venv/bin/python",
            "-B",
            str(binary / "gateway.py"),
            "cto-plan",
            "T-0002",
            "--project",
            "dev-001",
            "--gateway-dir",
            str(gateway),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (
        json.loads(result.stdout)["approval_state"] == "awaiting_development_approval"
    )


def test_existing_send_path_posts_one_text_without_new_connection(monkeypatch):
    calls = []

    class Response:
        status = 200

        def read(self, _):
            return b'{"ok":true,"messageId":"sent-1"}'

    class Connection:
        def __init__(self, host, port, timeout):
            calls.append((host, port, timeout))

        def request(self, method, path, body, headers):
            calls.append(
                (method, path, json.loads(body), headers["x-hermes-sidecar-token"])
            )

        def getresponse(self):
            return Response()

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(cto.http.client, "HTTPConnection", Connection)
    result = cto._send(
        {
            "owner_space_id": "bound-dm",
            "sidecar_port": 8789,
            "sidecar_token": "synthetic",
        },
        "plan text",
    )
    assert result == "sent-1"
    assert calls[0] == ("127.0.0.1", 8789, 3)
    assert calls[1][0:3] == (
        "POST",
        "/send",
        {"spaceId": "bound-dm", "text": "plan text", "format": "text"},
    )


def test_operator_destination_binding_uses_original_dm_digest(tmp_path, monkeypatch):
    request = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    monkeypatch.setattr(bind_delivery, "REQUEST", request)
    gateway = tmp_path / "gateway"
    processed = tmp_path / "processed"
    gateway.mkdir()
    processed.mkdir()
    (gateway / "journal.jsonl").write_text(
        json.dumps(
            {
                "kind": "outcome",
                "outcome": "filed",
                "project": "dev-001",
                "task_id": "T-0001",
                "request_id": request,
                "revision": 1,
                "file": request + ".json",
            }
        )
        + "\n"
    )
    (gateway / "v1-1-intake.json").write_text(
        json.dumps(
            {
                "sidecar_port": 8789,
                "sidecar_token": "synthetic-token",
            }
        )
    )
    space = "synthetic-original-dm"
    digest = hashlib.sha256(space.encode()).hexdigest()[:32]
    monkeypatch.setattr(bind_delivery, "ORIGINAL_DM_DIGEST", digest)
    envelope = {
        "protocol": "alfred.devreq/1",
        "request_id": request,
        "revision": 1,
        "submitted_at": "2026-10-15T00:00:00+00:00",
        "origin": {"interface": "photon", "conversation_ref": digest},
        "utterance": "Please add dark mode to the website",
        "project_hint": "dev-001",
        "intent_confidence": 0.9,
        "answers": [],
        "draft": {
            "title": "Add dark mode to website",
            "task_type": "feature",
            "objective": "Add dark mode.",
            "scope": "Frontend only.",
            "requirements": "Add a toggle.",
            "constraints": "No backend changes.",
            "acceptance_criteria": "- [ ] Toggle works.",
            "security_considerations": "No sensitive data.",
            "testing_requirements": "Check both themes.",
        },
    }
    (processed / f"{request}.json").write_text(json.dumps(envelope))
    with pytest.raises(cto.CTOError, match="does not match"):
        bind_delivery.bind("wrong-dm", gateway, processed)
    assert not (gateway / "v1-cto-delivery.json").exists()
    target = bind_delivery.bind(space, gateway, processed)
    assert json.loads(target.read_text())["owner_space_id"] == space
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        bind_delivery.bind(space, gateway, processed)
