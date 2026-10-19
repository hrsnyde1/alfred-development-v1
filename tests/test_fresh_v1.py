"""Fresh-task handoffs: real V1 workers, temporary Git, mocked models/Photon/GitHub.

The fixture never uses a live grant, owner event, GitHub destination or notifier.
Only model responses, remote APIs and privilege separation are replaced. Real
Developer/QA checks still run in their existing bubblewrap sandboxes.
"""

import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import intake
import pytest
import yaml
from alfred.gateway.dispatcher import GatewayConfig, run_once
from alfred.registry.loader import parse_registry

from completion_integration import runtime
from completion_integration.delivery import DeliveryTracker
from developer_v1 import pipeline, publication_approval, run_task
from developer_v1.gateway_adapter import read_gateway_inputs
from developer_v1.owner_grants import DevelopmentGrantIssuer, _phrase
from developer_v1.trusted_intake_development import IntakeGate, IntakeRefused
from draft_pr_publisher import worker as publisher
from fresh_v1 import host, role
from fresh_v1.handoffs import Held, advance, once
from fresh_v1.protected import protected_json, publication_plan_loader
from independent_qa import worker as qa
from independent_reviewer import worker as reviewer
from tests.test_draft_pr_publisher import FakeGitHub
from tests.test_independent_reviewer import model_answer
from v1_cto import cto

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "dev-v1-accept"
OWNER, SIDE, HERMES = "mock-owner", 9201, 9202


def git(repo, *args):
    return (
        subprocess.check_output(
            ["git", "-C", str(repo), *map(str, args)], stderr=subprocess.DEVNULL
        )
        .decode()
        .strip()
    )


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(publisher.canonical(value))
    path.chmod(0o600)


def event(identifier, text, target=None, **changes):
    return {
        "messageId": identifier,
        "direction": "inbound",
        "sender": {"id": OWNER},
        "space": {"id": "mock-dm", "type": "dm"},
        "content": {"type": "text", "text": text},
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "nativeReplyTargetGuid": target,
        "nativeIsForward": False,
        **changes,
    }


DRAFT = {
    "title": "Backend calculator multiply helper",
    "task_type": "feature",
    "objective": "Add backend multiply(a: int, b: int) -> int to calculator.py.",
    "scope": "In: calculator.py and test_calculator.py only.",
    "requirements": "Multiply integers, including negative values and zero; retain add and subtract.",
    "constraints": "Keep the existing interface and dependencies.",
    "acceptance_criteria": "- [ ] multiply handles positive integers, negatives and zero.\n"
    "- [ ] Existing add and subtract and unittest discovery pass.",
    "security_considerations": "No credential access or external input.",
    "testing_requirements": "Run python unittest discovery.",
}


class MultiplyBroker:
    def authenticated(self):
        return True

    def generate(self, choice, *, objective, sources, identity="", project_context=""):
        assert "multiply(a: int, b: int)" in objective
        assert (
            "def subtract" in sources["calculator.py"]
        )  # current main, not old checkout
        return {
            "edits": [
                {
                    "path": "calculator.py",
                    "content": sources["calculator.py"]
                    + "\ndef multiply(a: int, b: int) -> int:\n    return a * b\n",
                },
                {
                    "path": "test_calculator.py",
                    "content": sources["test_calculator.py"]
                    + "\nclass MultiplyTests(unittest.TestCase):\n"
                    "    def test_integers(self):\n"
                    "        for a, b, expected in [(7,3,21),(-7,3,-21),(-7,-3,21),(0,5,0)]:\n"
                    "            self.assertEqual(calculator.multiply(a,b), expected)\n",
                },
            ],
            "summary": "Added multiply with integer coverage",
        }


class World(host.Host):
    """Run Host's actual handoff preparation with disposable, same-UID workers."""

    def __init__(self, root):
        self.root = root
        self.repo = root / "home/Git/accept"
        shutil.copytree(ROOT / "v1_1a/fixture/dev-001", self.repo)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.name", "Fixture")
        git(self.repo, "config", "user.email", "fixture@example.invalid")
        (self.repo / "calculator.py").write_text("def add(a, b):\n    return a + b\n")
        (self.repo / "test_calculator.py").write_text(
            "import unittest\nimport calculator\nclass Existing(unittest.TestCase):\n"
            "    def test_add(self): self.assertEqual(calculator.add(7,3),10)\n"
        )
        # Reserve both historical IDs in the real Gateway allocator.
        for task in ("T-0001", "T-0002"):
            (self.repo / ".dev/tasks" / (task + "-historical.md")).write_text(
                "preserve " + task
            )
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "historical baseline")
        old = git(self.repo, "rev-parse", "HEAD")
        with (self.repo / "calculator.py").open("a") as stream:
            stream.write("\ndef subtract(a, b):\n    return a - b\n")
        git(self.repo, "add", "calculator.py")
        git(self.repo, "commit", "-qm", "separate owner merge on current main")
        self.main = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "--detach", old)
        data = yaml.safe_load(
            (ROOT / "v1_1a/fixture/registry.template.yaml").read_bytes()
        )
        data["projects"][0].update(id=PROJECT, local_path=str(self.repo))
        data["projects"][0]["repo"]["github"] = "fixtureowner/disposable"
        self.registry = parse_registry(data)
        reg = root / "registry.yaml"
        reg.write_text(yaml.safe_dump(data))
        reg.chmod(0o600)
        requests = root / "home/Alfred/projects/hermes-requests"
        (requests / "inbox").mkdir(parents=True)
        self.gateway = GatewayConfig(
            requests, root / "gateway", root / "home", "2026-10-16"
        )
        self.gateway.gateway_dir.mkdir()
        self.grants = root / "grants"
        self.grants.mkdir(mode=0o700)
        self.worktrees = root / "worktrees"
        self.worktrees.mkdir(mode=0o700)
        state = root / "developer-state"
        state.mkdir(mode=0o700)
        models = state / "models.json"
        models.write_bytes(
            (ROOT / "developer_v1/models.codex-verified.example.json").read_bytes()
        )
        models.chmod(0o600)
        jobs = root / "jobs"
        jobs.mkdir(mode=0o700)
        delivery = root / "delivery"
        delivery.mkdir(mode=0o700)
        tracker = DeliveryTracker(delivery)
        tracker.initialize()
        # Preserve a prior task's genuine uncertain state (mock transport timeout).
        from completion_integration.completion import CompletionNotification

        self.old_notice = CompletionNotification(
            project=PROJECT,
            task_id="T-0002",
            commit="old-revision",
            pr_url="old-url",
            summary="old",
            text="old",
        )
        tracker.deliver(self.old_notice, lambda _: None)
        self.old_delivery = json.loads((delivery / "delivery.json").read_bytes())[
            "records"
        ]
        gateway_code = root / "gateway-code"
        (gateway_code / ".dev/bin").mkdir(parents=True)
        for name in ("taskspec.py",):
            shutil.copyfile(
                Path("/home/alfred/Git/alfred/.dev/bin") / name,
                gateway_code / ".dev/bin" / name,
            )
        shutil.copyfile(
            ROOT / "v1_cto/plan.schema.json", gateway_code / ".dev/bin/plan.schema.json"
        )
        self.p = {
            "schema": "alfred.fresh-v1-policy/1",
            "enabled": True,
            "project": PROJECT,
            "destination": "fixtureowner/disposable",
            "base_branch": "main",
            "allowed_scope": ["calculator.py", "test_calculator.py"],
            "specialists": ["backend"],
            "total_cost_limit": 6,
            "repository": str(self.repo),
            "registry": str(reg),
            "gateway_root": str(gateway_code),
            "gateway_state": str(self.gateway.gateway_dir),
            "grant_root": str(self.grants),
            "worktree_root": str(self.worktrees),
            "developer_state": str(state),
            "models": str(models),
            "jobs": str(jobs),
            "completion_state": str(delivery),
            "publisher_token": str(root / "mock-token"),
            "qa_config": str(root / "qa-config.json"),
            "reviewer_config": str(root / "review-config.json"),
        }
        save(
            root / "qa-config.json",
            {
                "schema": "alfred.qa-config/1",
                "model": {"enabled": True},
                "projects": {
                    PROJECT: {
                        "checks": ["calculator_examples", "python_unittest"],
                        "criteria": [],
                    }
                },
            },
        )
        save(
            root / "review-config.json",
            {
                "schema": "alfred.reviewer-config/1",
                "model": {},
                "max_diff_bytes": 131072,
            },
        )
        self.policy_path = root / "policy.json"
        save(self.policy_path, self.p)
        self.uids = dict.fromkeys(host.USERS, os.geteuid())
        self.gids = dict.fromkeys(host.USERS, os.getegid())
        self.messages, self.calls, self.notifications, self.pushes = [], [], [], []
        self.development_issuer = DevelopmentGrantIssuer(
            self.grants,
            owner_sender_id=OWNER,
            sidecar_uid=SIDE,
            environment="staging",
            preview_sender=self.send,
        )
        self.publication_issuer = publication_approval.PublicationApprovalIssuer(
            self.grants,
            owner_sender_id=OWNER,
            sidecar_uid=SIDE,
            preview_sender=self.send,
            plan_verifier=publication_plan_loader(
                jobs, trusted_uid=os.geteuid(), trusted_root=root
            ),
        )
        self.gate = IntakeGate(
            owner_sender_id=OWNER,
            sidecar_uid=SIDE,
            hermes_uid=HERMES,
            intake_dir=requests,
            gateway_dir=self.gateway.gateway_dir,
            registry_path=reg,
            request_route_root=self.grants,
            preview_sender=self.send,
            development_issuer=self.development_issuer,
            publication_issuer=self.publication_issuer,
            development_inputs=lambda p, t: read_gateway_inputs(
                gateway_root=Path(self.p["gateway_root"]),
                gateway_state=self.gateway.gateway_dir,
                registry_path=reg,
                project_id=p,
                task_id=t,
            ),
        )
        self.bare = root / "mock-github.git"
        git(root, "init", "--bare", "-q", self.bare)
        git(self.repo, "push", "-q", self.bare, f"{self.main}:refs/heads/main")
        self.github = FakeGitHub(self.bare, self.p["destination"])
        self.qa_decision, self.review_decision, self.transport_receipt = (
            "PASS",
            "APPROVED",
            "mock-receipt",
        )

    def send(self, space, text):
        self.messages.append((space, text))
        return f"mock-challenge-{len(self.messages)}"

    def directory(self, path, user=None):
        if not path.parent.exists():
            self.directory(path.parent)
        path.mkdir(mode=0o700, parents=True, exist_ok=False)

    def share(self, path, users):
        pass  # Only the real multi-UID boundary is replaced in this fixture.

    def guard(self):
        with patch.object(
            host,
            "protected_json",
            lambda path: protected_json(
                path, trusted_uid=os.geteuid(), trusted_root=self.root
            ),
        ):
            return super().guard()

    def intake(self, payload):
        self.guard()
        return self.gate.dispatch(payload, 0)

    def submit(self, text=None, identifier="mock-request"):
        message = event(
            identifier,
            text or f"Please add a backend multiply helper in {PROJECT}.",
        )
        self.gate.dispatch({"op": "observe", "event": message}, SIDE)
        response = self.gate.dispatch(
            {
                "op": "submit",
                "event_id": message["messageId"],
                "text_digest": hashlib.sha256(
                    message["content"]["text"].encode()
                ).hexdigest(),
                "draft": DRAFT,
            },
            HERMES,
        )
        assert response["state"] == "awaiting_confirmation"
        assert not list((self.gateway.intake_dir / "inbox").glob("*.json"))
        self.gate.dispatch(
            {
                "op": "observe",
                "event": event(
                    "mock-confirm-" + identifier,
                    "Yes, go ahead",
                    self.gate._active.preview_id,
                ),
            },
            SIDE,
        )
        report = run_once(self.registry, intake.IntakeFiler(), self.gateway)
        assert len(report.filed) == 1, report
        task = report.filed[0]
        assert task not in {"T-0001", "T-0002"}
        root = Path(self.p["jobs"]) / PROJECT / task
        self.directory(root)
        self.job = {
            "project": PROJECT,
            "task_id": task,
            "request_id": response["request_id"],
            "owner_id": OWNER,
            "space_id": "mock-dm",
        }
        self.freeze_json(root / "job.json", self.job)
        return task

    def approve_development(self, identifier="mock-dev-owner-reply"):
        challenge = json.loads(
            (self.jobdir(self.job) / "development-challenge.result.json").read_bytes()
        )
        receipt = json.loads(
            (self.grants / f"challenge-{challenge['challenge']}.json").read_bytes()
        )
        self.gate.dispatch(
            {
                "op": "observe",
                "event": event(
                    identifier,
                    _phrase(receipt["request"]),
                    challenge["message_id"],
                ),
            },
            SIDE,
        )

    def approve_publication(self, identifier="mock-pub-owner-reply"):
        root = self.jobdir(self.job)
        challenge = json.loads(
            (root / "publication-challenge.result.json").read_bytes()
        )
        plan = json.loads((root / "publication/approved-plan.json").read_bytes())
        text = publication_approval._phrase(challenge["challenge"], plan)
        self.gate.dispatch(
            {
                "op": "observe",
                "event": event(identifier, text, challenge["message_id"]),
            },
            SIDE,
        )

    def worker(self, job, stage, user, fix_round=0):
        self.guard()
        self.dispatched = True  # As Host.worker, immediately before the role starts.
        self.calls.append((stage, user))
        real_execute, real_review, real_publish, real_notify = (
            pipeline.execute_gateway_task,
            reviewer.run,
            publisher.publish,
            runtime.run,
        )

        def develop(**kwargs):
            # Never the host's own team-skills library (root-owned, delivered live).
            return real_execute(
                **kwargs, broker=MultiplyBroker(), grant_environment="staging",
                team_skills_root=self.root / "no-team-skills",
            )

        def independent_model(config, context):
            decision = (
                self.qa_decision.pop(0)
                if isinstance(self.qa_decision, list)
                else self.qa_decision
            )
            findings = (
                []
                if decision == "PASS"
                else [
                    {
                        "severity": "high",
                        "requirement": "coverage",
                        "detail": "mock finding",
                    }
                ]
            )
            return {"provider": "codex", "model": "independent-qa-fixture"}, findings

        def review_model(context):
            answer, used = model_answer(context)
            answer["decision"] = (
                self.review_decision.pop(0)
                if isinstance(self.review_decision, list)
                else self.review_decision
            )
            answer["findings"] = list(getattr(self, "review_findings", []))
            return answer, used

        def local_push(source, plan, token):
            self.pushes.append(plan["publication_branch"])
            git(
                source,
                "push",
                "-q",
                self.bare,
                f"{plan['final_revision']}:refs/heads/{plan['publication_branch']}",
            )

        def notify(path, **kwargs):
            def send(notice):
                self.notifications.append(notice.text)
                return self.transport_receipt

            return real_notify(
                path,
                **kwargs,
                trusted_uid=os.geteuid(),
                trusted_root=self.root,
                # A PR the fixture merged (handoff.31) reads back as merged.
                get_pr=lambda repo, number: {
                    "merged": False,
                    "merged_at": None,
                    **self.github.pr_list[0],
                },
                sender_factory=lambda _: send,
                paused_check=lambda: True,
            )

        with contextlib.ExitStack() as stack:
            stack.enter_context(
                patch.object(
                    role,
                    "protected_json",
                    lambda path: protected_json(
                        path, trusted_uid=os.geteuid(), trusted_root=self.root
                    ),
                )
            )
            if stage == "plan":
                # Planning never pins the host's own team-skills library either.
                real_attach = role.team_skills.attach
                stack.enter_context(
                    patch.object(
                        role.team_skills,
                        "attach",
                        lambda plan, spec, specialists, *a, **kw: real_attach(
                            plan, spec, specialists, self.root / "no-team-skills"
                        ),
                    )
                )
                original = role.prepare_plan
                stack.enter_context(
                    patch.object(
                        role,
                        "prepare_plan",
                        lambda job, policy: original(
                            job, policy, remote_main=self.main, fetch=False
                        ),
                    )
                )
            stack.enter_context(patch.object(run_task, "execute_gateway_task", develop))
            stack.enter_context(
                patch.object(qa, "analyze_with_model", independent_model)
            )
            stack.enter_context(
                patch.object(
                    reviewer,
                    "run",
                    lambda *args: real_review(*args, model_runner=review_model),
                )
            )
            stack.enter_context(
                patch.object(
                    publisher,
                    "publish",
                    lambda **kwargs: real_publish(
                        **kwargs,
                        github=self.github,
                        pusher=local_push,
                        trusted_uid=os.geteuid(),
                        trusted_root=self.root,
                    ),
                )
            )
            stack.enter_context(patch.object(runtime, "run", notify))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                try:
                    role.main(
                        [
                            stage,
                            "--job",
                            str(self.jobdir(job)),
                            "--policy",
                            str(self.policy_path),
                            *(["--round", str(fix_round)] if fix_round else []),
                        ]
                    )
                except Exception as exc:
                    import traceback

                    traceback.print_exc()
                    print(
                        stage,
                        getattr(exc, "detail", None),
                        file=__import__("sys").stderr,
                    )
                    raise
            return json.loads(output.getvalue().splitlines()[-1])

    def tick(self):
        return advance(self.jobdir(self.job), self.job, self)


@pytest.fixture
def world(tmp_path):
    previous = os.umask(0o077)
    try:
        yield World(tmp_path)
    finally:
        os.umask(previous)


def test_native_request_to_real_workers_draft_and_completion(world):
    task = world.submit()
    assert world.tick() == {"state": "awaiting_development_approval"}
    assert world.calls == [("plan", "alfred")]
    assert DRAFT["objective"] in world.messages[1][1]
    assert world.main in world.messages[1][1] and "Approach:" in world.messages[1][1]
    world.approve_development()
    assert world.tick() == {"state": "awaiting_publication_approval"}
    assert not world.pushes and not world.notifications
    world.approve_publication()
    result = world.tick()
    assert result["state"] == "complete", result
    assert len(world.pushes) == len(world.notifications) == 1
    assert [
        u for s, u in world.calls if s in {"developer", "qa", "reviewer", "publish"}
    ] == ["alfred", "alfredqa", "alfredreview", "alfredpublish"]
    # Plain language for the owner: no task number, clearly not live.
    assert task not in world.notifications[0]
    assert "ready for you to push" in world.notifications[0]
    assert world.tick()["state"] == "complete"
    assert (
        len(world.messages) == 3 and len(world.pushes) == len(world.notifications) == 1
    )
    records = json.loads(
        (Path(world.p["completion_state"]) / "delivery.json").read_bytes()
    )["records"]
    assert len(records) == 2
    for key, record in world.old_delivery.items():
        assert records[key] == record
    for old in ("T-0001", "T-0002"):
        assert (
            world.repo / ".dev/tasks" / (old + "-historical.md")
        ).read_text() == "preserve " + old


@pytest.mark.parametrize(
    "text",
    ["Please develop a multiply helper", "Please develop this in another-project"],
)
def test_missing_project_fails_closed(world, text):
    with pytest.raises(IntakeRefused):
        world.submit(text)
    assert not world.messages


@pytest.mark.parametrize(
    "stage,decision", [("qa", "FAIL"), ("reviewer", "CHANGES_REQUESTED")]
)
def test_failed_independent_stage_stops_publication(world, stage, decision):
    world.submit()
    world.tick()
    world.approve_development()
    setattr(world, stage.replace("reviewer", "review") + "_decision", decision)
    result = world.tick()
    # Every automatic fix round failed too: nothing is published, and the owner
    # gets one plain-language text instead of a publication approval.
    assert result == {"state": "held", "reason": "fix rounds exhausted; owner notified"}
    assert not world.pushes and not world.notifications
    assert len(world.messages) == 3
    assert world.messages[-1][1].startswith("I couldn't finish this one:")
    assert "Approve GitHub Draft PR" not in world.messages[-1][1]


def test_uncertain_completion_never_retries_after_restart(world):
    world.submit()
    world.tick()
    world.approve_development()
    world.tick()
    world.approve_publication()
    world.transport_receipt = None
    assert world.tick()["state"] == "held"
    before = list(world.notifications)
    # Re-read only durable files; advance carries no process-local stage state.
    assert advance(world.jobdir(world.job), dict(world.job), world)["state"] == "held"
    assert world.notifications == before and len(world.pushes) == 1


def test_crash_between_attempt_and_result_is_not_replayed(tmp_path):
    calls = []

    def crash():
        calls.append(1)
        raise TimeoutError("ambiguous remote result")

    with pytest.raises(TimeoutError):
        once(tmp_path, "publisher", crash)
    with pytest.raises(Held):
        once(tmp_path, "publisher", lambda: calls.append(2))
    assert calls == [1]


def test_cto_prepare_only_does_not_send(world):
    world.submit()
    sends = []
    counts = cto.poll(
        gateway_dir=world.gateway.gateway_dir,
        registry_path=Path(world.p["registry"]),
        config_path=world.root / "absent-delivery-config",
        sender=lambda *args: sends.append(args),
        prepare_only=True,
    )
    assert counts["planned"] == 1 and not sends


def test_two_registered_projects_are_ambiguous(world):
    data = yaml.safe_load(Path(world.p["registry"]).read_bytes())
    other = json.loads(json.dumps(data["projects"][0]))
    other.update(id="other-project", local_path=str(world.root / "other"))
    other["repo"]["github"] = "fixtureowner/other"
    data["projects"].append(other)
    Path(world.p["registry"]).write_text(yaml.safe_dump(data))
    with pytest.raises(IntakeRefused):
        world.submit(
            f"Please add a backend helper to project {PROJECT} or other-project"
        )
    assert not world.messages


@pytest.mark.parametrize(
    "changes",
    [
        {"nativeIsForward": True},
        {"sender": {"id": "impostor"}},
        {"space": {"id": "other", "type": "dm"}},
        {"timestamp": "2000-01-01T00:00:00Z"},
        {"nativeReplyTargetGuid": None},
        {"nativeReplyTargetGuid": "unrelated"},
    ],
)
def test_new_development_grant_requires_fresh_native_owner_reply(world, changes):
    world.submit()
    world.tick()
    challenge = json.loads(
        (world.jobdir(world.job) / "development-challenge.result.json").read_bytes()
    )
    receipt = json.loads(
        (world.grants / f"challenge-{challenge['challenge']}.json").read_bytes()
    )
    reply = event(
        "mock-bad-reply",
        _phrase(receipt["request"]),
        challenge["message_id"],
        **changes,
    )
    try:
        world.gate.dispatch({"op": "observe", "event": reply}, SIDE)
    except IntakeRefused:
        pass
    assert not list(world.grants.glob("grant-*.json"))
    assert world.tick()["state"] == "awaiting_development_approval"
    assert world.calls == [("plan", "alfred")]


def test_nonprivileged_client_cannot_issue_either_challenge(world):
    for op in (
        "stage_development_approval",
        "stage_publication_approval",
        "prepare_publication_authorization",
    ):
        for uid in (SIDE, HERMES, os.geteuid()):
            if uid == 0:
                continue
            with pytest.raises(IntakeRefused):
                world.gate.dispatch({"op": op}, uid)
    assert not world.messages


def test_changed_approved_plan_cannot_execute(world):
    world.submit()
    world.tick()
    world.approve_development()
    plan = (
        world.gateway.gateway_dir
        / "cto-plans"
        / f"{PROJECT}-{world.job['task_id']}.json"
    )
    raw = json.loads(plan.read_bytes())
    raw["objective"] += " changed after approval"
    save(plan, raw)
    assert world.tick()["state"] == "held"
    assert not list(world.grants.glob("execution-*.json"))
    assert not world.notifications and not world.pushes


def test_publication_reply_cannot_reuse_development_event_or_forward(world):
    world.submit()
    world.tick()
    world.approve_development()
    world.tick()
    challenge = json.loads(
        (world.jobdir(world.job) / "publication-challenge.result.json").read_bytes()
    )
    plan = json.loads(
        (world.jobdir(world.job) / "publication/approved-plan.json").read_bytes()
    )
    for identifier, changes in [
        ("mock-dev-owner-reply", {}),
        ("fresh-but-forwarded", {"nativeIsForward": True}),
    ]:
        reply = event(
            identifier,
            publication_approval._phrase(challenge["challenge"], plan),
            challenge["message_id"],
            **changes,
        )
        with pytest.raises(IntakeRefused):
            world.gate.dispatch({"op": "observe", "event": reply}, SIDE)
    assert not list(world.grants.glob("publication-decision-*.json"))
    assert not (world.jobdir(world.job) / "publication/authorization.json").exists()
    assert world.tick()["state"] == "awaiting_publication_approval"
    assert not world.pushes and not world.notifications


def test_changed_publication_seal_fails_before_owner_authorization(world):
    world.submit()
    world.tick()
    world.approve_development()
    world.tick()
    root = world.jobdir(world.job)
    seal = json.loads((root / "publication/seal.json").read_bytes())
    seal["publication_plan_sha256"] = "0" * 64
    save(root / "publication/seal.json", seal)
    with pytest.raises(IntakeRefused):
        world.approve_publication()
    assert not (root / "publication/authorization.json").exists() and not world.pushes


def test_changed_remote_main_blocks_push_and_notification(world):
    world.submit()
    world.tick()
    world.approve_development()
    world.tick()
    world.approve_publication()
    # Remote main no longer equals the exact plan approved by both owners.
    old = git(world.repo, "rev-parse", "HEAD")
    git(world.bare, "update-ref", "refs/heads/main", old)
    assert world.tick()["state"] == "held"
    assert not world.pushes and not world.notifications
    result = (
        world.jobdir(world.job)
        / "publisher-output"
        / PROJECT
        / world.job["task_id"]
        / "publication-result.json"
    )
    original = result.read_bytes()
    assert json.loads(original)["status"] == "ERROR"
    world.tick()
    assert result.read_bytes() == original and not world.pushes


def test_protected_inputs_reject_symlink_and_digest_mismatch(tmp_path):
    root = tmp_path / "protected"
    root.mkdir(mode=0o700)
    path = root / "input.json"
    save(path, {"a": 1})
    link = root / "link.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        protected_json(link, trusted_uid=os.geteuid(), trusted_root=root)
    path.chmod(0o666)
    with pytest.raises(ValueError):
        protected_json(path, trusted_uid=os.geteuid(), trusted_root=root)


def test_unfinished_operation_survives_a_new_python_process(tmp_path):
    with pytest.raises(TimeoutError):
        once(tmp_path, "completion", lambda: (_ for _ in ()).throw(TimeoutError()))
    result = subprocess.run(
        [
            "/usr/bin/python3",
            "-c",
            (
                "from pathlib import Path;from fresh_v1.handoffs import once,Held;import sys;"
                "\ntry: once(Path(sys.argv[1]),'completion',lambda:sys.exit(99))"
                "\nexcept Held:sys.exit(0)"
            ),
            str(tmp_path),
        ],
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0


def test_disabled_example_cannot_dispatch():
    assert (
        json.loads((ROOT / "fresh_v1/config.example.json").read_bytes())["enabled"]
        is False
    )


def test_two_fresh_tasks_have_separate_approvals_and_delivery_without_reset(world):
    first = world.submit()
    world.tick()
    world.approve_development()
    world.tick()
    world.approve_publication()
    assert world.tick()["state"] == "complete"
    old_decisions = {p: p.read_bytes() for p in world.grants.glob("*decision-*.json")}
    old_job = world.jobdir(world.job)
    old_result = (old_job / "publisher.result.json").read_bytes()
    world.github.pr_list = []  # Mock the branch-specific PR query for the new branch.
    second = world.submit(identifier="mock-second-owner-request")
    assert second != first and second not in {"T-0001", "T-0002"}
    assert world.tick()["state"] == "awaiting_development_approval"
    world.approve_development("mock-second-development-reply")
    assert world.tick()["state"] == "awaiting_publication_approval"
    world.approve_publication("mock-second-publication-reply")
    assert world.tick()["state"] == "complete"
    assert all(p.read_bytes() == original for p, original in old_decisions.items())
    assert (old_job / "publisher.result.json").read_bytes() == old_result
    assert len(world.pushes) == len(world.notifications) == 2
    records = json.loads(
        (Path(world.p["completion_state"]) / "delivery.json").read_bytes()
    )["records"]
    assert len(records) == 3
    for key, record in world.old_delivery.items():
        assert records[key] == record


def test_pause_stops_next_handoff_without_reusing_grant(world):
    world.submit()
    world.tick()
    world.approve_development()
    (world.gateway.gateway_dir / "PAUSE").touch()
    assert world.tick()["state"] == "held"
    assert not list(world.grants.glob("execution-*.json"))
    assert not world.pushes and not world.notifications


def test_disabled_policy_stops_each_dispatch(world):
    world.submit()
    world.tick()
    world.approve_development()
    policy = dict(world.p)
    policy["enabled"] = False
    save(world.policy_path, policy)
    assert world.tick()["state"] == "held"
    assert world.calls == [("plan", "alfred")]
    assert not list(world.grants.glob("execution-*.json"))


def test_expired_publication_reply_cannot_create_authorization(world):
    world.submit()
    world.tick()
    world.approve_development()
    world.tick()
    current = world.publication_issuer.clock()
    with (
        patch.object(world.publication_issuer, "clock",
                     return_value=current + publication_approval.SIMPLE_MAX_AGE + 1),
        pytest.raises(IntakeRefused),
    ):
        world.approve_publication()
    assert not list(world.grants.glob("publication-decision-*.json"))
    assert not (world.jobdir(world.job) / "publication/authorization.json").exists()


def test_filing_status_and_next_request_are_project_aware_without_status_poll(world):
    first = world.submit()
    # Never call status: observing the next genuine SDK turn retires the filing.
    second = world.submit(identifier="mock-another-native-owner-turn")
    assert first != second
    message = world.gate._active
    status = world.gate.dispatch(
        {
            "op": "status",
            "event_id": message.message_id,
            "text_digest": message.text_digest,
        },
        HERMES,
    )
    assert status["state"] == "filed" and status["task_id"] == second
    assert status["project"] == PROJECT


def test_existing_timer_poll_uses_only_native_confirmed_filing(world):
    world.submit()
    save(world.gateway.gateway_dir / "v1-1-intake.json", {"owner_sender_id": OWNER})
    journal = world.gateway.gateway_dir / "journal.jsonl"
    with journal.open("ab") as stream:
        stream.write(
            json.dumps(
                {
                    "kind": "outcome",
                    "outcome": "filed",
                    "project": PROJECT,
                    "task_id": "T-0002",
                    "request_id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
                    "revision": 1,
                }
            ).encode()
            + b"\n"
        )

    def test_root_directory(path):
        assert path == Path(world.p["jobs"]) and path.stat().st_uid == os.geteuid()

    with (
        patch.object(host, "require_root"),
        patch.object(host, "root_directory", test_root_directory),
        patch.object(
            host,
            "protected_json",
            lambda p: protected_json(
                p, trusted_uid=os.geteuid(), trusted_root=world.root
            ),
        ),
        patch.object(host, "Host", return_value=world),
        patch.object(
            host.pwd, "getpwnam", return_value=type("Photon", (), {"pw_uid": SIDE})()
        ),
    ):
        assert host.poll(world.policy_path)["state"] == "awaiting_development_approval"
        assert host.poll(world.policy_path)["state"] == "awaiting_development_approval"
    assert world.calls == [("plan", "alfred")]
    assert not (Path(world.p["jobs"]) / PROJECT / "T-0002").exists()


def test_planning_fetches_current_main_without_resetting_canonical_checkout(world):
    world.submit()
    old_head = git(world.repo, "rev-parse", "HEAD")
    original = role.git

    def local_fetch(repo, *args):
        args = [
            str(world.bare) if a == "https://fixtureowner/disposable.git" else a
            for a in args
        ]
        args = [
            str(world.bare)
            if a == "https://github.com/fixtureowner/disposable.git"
            else a
            for a in args
        ]
        return original(repo, *args)

    with patch.object(role, "git", local_fetch):
        plan = role.prepare_plan(world.job, world.p, remote_main=world.main, fetch=True)
    assert plan["baseline_revision"] == world.main != old_head
    assert git(world.repo, "rev-parse", "HEAD") == old_head
    assert git(world.repo, "rev-parse", "refs/remotes/alfred-v1/main") == world.main
    assert not list(world.grants.glob("grant-*.json"))


def test_approved_plan_baseline_is_used_even_without_caller_override(world):
    world.submit()
    world.tick()
    world.approve_development()
    root = world.jobdir(world.job)
    context = json.loads((root / "context.json").read_bytes())
    challenge = json.loads((root / "development-challenge.result.json").read_bytes())
    inputs = read_gateway_inputs(
        gateway_root=Path(world.p["gateway_root"]),
        gateway_state=world.gateway.gateway_dir,
        registry_path=Path(world.p["registry"]),
        project_id=PROJECT,
        task_id=world.job["task_id"],
    )
    kwargs = {
        "project": PROJECT,
        "task_id": world.job["task_id"],
        "worktree_root": world.worktrees / f"fresh-{PROJECT}-{world.job['task_id']}",
        "scope": context["scope"],
        "grant_reference": challenge["challenge"],
        "grant_root": world.grants,
        "items": [
            {
                "id": "backend-main",
                "specialist": "backend",
                "files": context["scope"],
                "depends_on": [],
                "objective": DRAFT["objective"],
            }
        ],
        "models": json.loads(Path(world.p["models"]).read_bytes()),
        "state_root": Path(world.p["developer_state"]),
        "total_cost_limit": 6,
        "broker": MultiplyBroker(),
        "grant_environment": "staging",
    }
    from developer_v1.router import Denied

    with pytest.raises(Denied):
        pipeline.execute_approved(
            inputs, **kwargs, baseline_revision=git(world.repo, "rev-parse", "HEAD")
        )
    assert not list(world.grants.glob("execution-*.json"))
    _, manifest = pipeline.execute_approved(inputs, **kwargs)
    report = manifest["developer_reports"][0]
    assert report["baseline_revision"] == world.main


def test_cto_summary_evidence_is_bound_to_exact_plan_and_bounded_before_send(world):
    world.submit()
    world.tick()
    root = world.jobdir(world.job)
    challenge = json.loads((root / "development-challenge.result.json").read_bytes())
    path = world.grants / f"challenge-{challenge['challenge']}.json"
    receipt = json.loads(path.read_bytes())
    assert (
        hashlib.sha256(receipt["plan_raw"].encode()).hexdigest()
        == receipt["request"]["plan_sha256"]
    )
    world.approve_development()
    receipt["plan_raw"] += " "
    save(path, receipt)
    assert world.tick()["state"] == "held"
    assert not list(world.grants.glob("execution-*.json"))


def test_oversized_cto_plan_evidence_is_refused_before_any_send(world):
    from developer_v1.approval_transition import approval_request
    from developer_v1.owner_grants import _bytes
    from developer_v1.router import Denied

    world.submit()
    context = role.prepare_plan(world.job, world.p, remote_main=world.main, fetch=False)
    plan_path = (
        world.gateway.gateway_dir
        / "cto-plans"
        / f"{PROJECT}-{world.job['task_id']}.json"
    )
    plan = json.loads(plan_path.read_bytes())
    plan["owner_summary"] = "x" * 16000
    raw_plan = _bytes(plan)
    worktrees = world.worktrees / "oversize"
    worktrees.mkdir(mode=0o700)
    inputs = read_gateway_inputs(
        gateway_root=Path(world.p["gateway_root"]),
        gateway_state=world.gateway.gateway_dir,
        registry_path=Path(world.p["registry"]),
        project_id=PROJECT,
        task_id=world.job["task_id"],
    )
    request = approval_request(
        inputs.spec_raw,
        raw_plan,
        project=PROJECT,
        task_id=world.job["task_id"],
        repository=world.repo,
        worktree_root=worktrees,
        scope=context["scope"],
        spec_decoder=inputs.spec_decoder,
    )
    before = list(world.messages)
    with pytest.raises(Denied):
        world.development_issuer.stage(
            request, space_id="mock-dm", peer_uid=0, plan_raw=raw_plan
        )
    assert world.messages == before and not list(world.grants.glob("challenge-*.json"))
