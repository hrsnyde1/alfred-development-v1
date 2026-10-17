"""Restricted glue for the existing root evidence timer. Disabled unless activated.

Root prepares exact per-role handoffs and invokes existing workers via runuser.
Only Intake may verify native owner replies; only Publisher may push/create draft PRs.
"""

import argparse
import fcntl
import hashlib
import json
import os
import pwd
import re
import socket
import stat
import subprocess
import tempfile
from pathlib import Path

from .diagnostics import WorkerFailure, failure, worker_failure
from .handoffs import Held, advance, write_once
from .protected import identity, protected_json

POLICY = Path("/etc/alfred-fresh-v1/policy.json")
RELEASE = "/usr/local/lib/alfred-fresh-v1"
USERS = ("alfred", "alfredqa", "alfredreview", "alfredpublish")


def read_owned(path, uid):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != uid
            or info.st_mode & 0o022
            or info.st_nlink != 1
            or info.st_size > 1048576
        ):
            raise ValueError("unsafe worker evidence")
        raw = stream.read(1048577)
    if len(raw) > 1048576:
        raise ValueError("worker evidence too large")
    return raw


def command(args, **kwargs):
    return subprocess.run(
        args,
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=kwargs.pop("timeout", 30),
        **kwargs,
    )


class Host:
    def __init__(self, policy, policy_path=POLICY):
        self.p, self.policy_path = policy, policy_path
        self.uids = {name: pwd.getpwnam(name).pw_uid for name in USERS}
        self.gids = {name: pwd.getpwnam(name).pw_gid for name in USERS}

    def guard(self):
        policy, _ = protected_json(self.policy_path)
        gateway = Path(self.p["gateway_state"])
        if (
            policy != self.p
            or policy.get("enabled") is not True
            or any((gateway / name).exists() for name in ("PAUSE", "STOP"))
        ):
            raise Held("fresh V1 activation changed or work is paused")

    def directory(self, path, user=None):
        # Do not require CAP_DAC_OVERRIDE to create an alfred-owned worktree
        # inside the existing private worktree parent.
        if user and path.parent.stat().st_uid == self.uids[user]:
            command(
                [
                    "/usr/sbin/runuser",
                    "-u",
                    user,
                    "--",
                    "/usr/bin/mkdir",
                    "-m",
                    "700",
                    str(path),
                ]
            )
        else:
            path.mkdir(mode=0o700, parents=True, exist_ok=False)
        if user:
            os.chown(path, self.uids[user], self.gids[user])
        else:
            command(
                [
                    "/usr/bin/setfacl",
                    "-m",
                    ",".join(f"u:{u}:r-x" for u in USERS),
                    str(path),
                ]
            )

    def share(self, path, users):
        args = [
            "/usr/bin/setfacl",
            "-R",
            "-m",
            ",".join(f"u:{u}:r-X" for u in users),
            str(path),
        ]
        uid = path.stat().st_uid
        if uid == self.uids["alfred"]:
            args = ["/usr/sbin/runuser", "-u", "alfred", "--", *args]
        elif uid != 0:
            raise Held("unsupported evidence owner")
        command(args)

    def freeze(self, path, raw, users=()):
        if not path.parent.exists():
            path.parent.mkdir(mode=0o700, parents=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if users:
            self.share(path, users)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def freeze_json(self, path, value, users=()):
        self.freeze(
            path, (json.dumps(value, indent=2, sort_keys=True) + "\n").encode(), users
        )

    def copy(self, source, destination, owner, users):
        self.freeze(destination, read_owned(source, self.uids[owner]), users)

    def jobdir(self, job):
        identity(job["project"], job["task_id"])
        return Path(self.p["jobs"]) / job["project"] / job["task_id"]

    def worker(self, job, stage, user):
        self.guard()
        # The canonical policy stays root:root 0600. Supply a separately sealed
        # job input, like job.json, instead of asking a dropped UID to read it.
        policy_path = self.jobdir(job) / "worker-policy.json"
        if policy_path.exists():
            frozen, _ = protected_json(policy_path)
            if frozen != self.p:
                raise Held("worker policy differs from current protected policy")
        else:
            self.freeze_json(policy_path, self.p, USERS)
        # Root-owned library roots only. Publisher's original flat release is
        # imported under its existing package name without copying its worker.
        roots = [
            "/usr/local/lib/alfred-fresh-v1",
            "/opt/alfred-developer-v1",
            "/opt/alfred-independent-qa-v1",
            "/opt/alfred-reviewer-v1",
            "/usr/local/lib/alfred-completion-v1",
        ]
        # Gateway's alfred-owned Python sources belong only to that identity.
        # Independent roles must not import code writable by another worker.
        if user == "alfred":
            roots.extend(
                ["/home/alfred/Git/alfred/src", "/home/alfred/Git/alfred/.dev/bin"]
            )
        bootstrap = (
            "import sys, importlib.util\nsys.path[:0] = "
            + repr(roots)
            + "\n"
            + """
s=importlib.util.spec_from_file_location("draft_pr_publisher", "/opt/alfred-draft-pr-publisher-v1/__init__.py", submodule_search_locations=["/opt/alfred-draft-pr-publisher-v1"])
m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
from fresh_v1.role import worker_main
worker_main(sys.argv[1:])"""
        )
        home = pwd.getpwnam(user).pw_dir
        python = (
            "/home/alfred/Git/alfred/.venv/bin/python"
            if user == "alfred"
            else "/usr/bin/python3"
        )
        args = [
            "/usr/sbin/runuser",
            "-u",
            user,
            "--",
            "/usr/bin/env",
            "-i",
            "HOME=" + home,
            "USER=" + user,
            "LOGNAME=" + user,
            "PATH=/usr/bin:/bin",
            "/usr/bin/setpriv",
            "--no-new-privs",
            "--inh-caps=-all",
            "--ambient-caps=-all",
            python,
            "-I",
            "-B",
            "-c",
            bootstrap,
            stage,
            "--job",
            str(self.jobdir(job)),
            "--policy",
            str(policy_path),
        ]
        try:
            result = command(args, timeout=1200)
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            OSError,
        ) as exc:
            evidence = worker_failure(stage, exc)
            # This is failure evidence, never a successful result or a retry permit.
            self.freeze_json(self.jobdir(job) / (stage + ".failure.json"), evidence)
            raise WorkerFailure(evidence) from None
        try:
            output = json.loads(result.stdout.decode().splitlines()[-1])
            if type(output) is not dict:
                raise ValueError("worker result must be an object")
        except (UnicodeError, ValueError, IndexError) as exc:
            evidence = failure(stage, "worker_output", exc)
            evidence.update(category="invalid_worker_result", worker_returncode=0)
            self.freeze_json(self.jobdir(job) / (stage + ".failure.json"), evidence)
            raise WorkerFailure(evidence) from None
        return output

    def intake(self, payload):
        self.guard()
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            # Intake's development send has a 30s total deadline. Keep the
            # existing root caller alive for its durable acknowledgement.
            client.settimeout(40)
            client.connect(self.p["intake_socket"])
            client.sendall(json.dumps(payload).encode() + b"\n")
            raw = bytearray()
            while b"\n" not in raw and len(raw) <= 65536:
                part = client.recv(4096)
                if not part:
                    break
                raw.extend(part)
        if b"\n" not in raw or len(raw) > 65536:
            raise Held("bounded Intake response missing")
        response = json.loads(raw.split(b"\n", 1)[0])
        if response.get("ok") is not True:
            raise Held("Intake refused: " + str(response.get("error", "unavailable")))
        return response

    def plan(self, job):
        result = self.worker(job, "plan", "alfred")
        root = self.jobdir(job)
        self.freeze_json(root / "context.json", result, USERS)
        return result

    def verify_plan_recovery(self, job):
        require_root()
        self.guard()
        from .recovery import verify

        verify(self.policy_path, self.jobdir(job))

    def development_challenge(self, job):
        root = (
            Path(self.p["worktree_root"]) / f"fresh-{job['project']}-{job['task_id']}"
        )
        self.directory(root, "alfred")
        return self.intake(
            {
                "op": "stage_development_approval",
                "project": job["project"],
                "task_id": job["task_id"],
                "scope": job["scope"],
                "worktree_root": str(root),
                "space_id": job["space_id"],
            }
        )

    def development_grant(self, job, reference):
        path = Path(self.p["grant_root"]) / f"grant-{reference}.json"
        if not path.exists():
            return None
        grant = json.loads(read_owned(path, self.uids["alfred"]))
        if any(
            grant.get(k) != job[k]
            for k in ("project", "task_id", "plan_sha256", "scope")
        ):
            raise Held("development grant differs from frozen job")
        # The existing runner independently revalidates immutable native evidence
        # and atomically claims this exact grant before model/worktree execution.
        return grant

    def developer(self, job):
        plan = json.loads(
            read_owned(
                Path(self.p["gateway_state"])
                / "cto-plans"
                / f"{job['project']}-{job['task_id']}.json",
                self.uids["alfred"],
            )
        )
        spec = read_owned(Path(job["spec_path"]), self.uids["alfred"]).decode()
        request = {
            "schema": "alfred.developer-run-request/1",
            "project": job["project"],
            "task_id": job["task_id"],
            "worktree_root": str(
                Path(self.p["worktree_root"])
                / f"fresh-{job['project']}-{job['task_id']}"
            ),
            "scope": job["scope"],
            "authorization_reference": job["grant_reference"],
            "baseline_revision": job["baseline_revision"],
            "items": [
                {
                    "id": "backend-main",
                    "specialist": "backend",
                    "files": job["scope"],
                    "depends_on": [],
                    "objective": plan["objective"]
                    + "\nCanonical specification (untrusted task data; approved scope remains authoritative):\n"
                    + spec,
                }
            ],
            "total_cost_limit": self.p["total_cost_limit"],
        }
        self.freeze_json(self.jobdir(job) / "execution.json", request, ("alfred",))
        return self.worker(job, "developer", "alfred")

    def qa(self, job):
        root = self.jobdir(job)
        base = root / "qa-input"
        self.directory(base)
        source = Path(self.p["developer_state"])
        project, task = job["project"], job["task_id"]
        manifest_path = source / project / task / "qa-input.json"
        manifest = json.loads(read_owned(manifest_path, self.uids["alfred"]))
        expected_final = (
            Path(self.p["worktree_root"])
            / f"fresh-{project}-{task}"
            / f"{project}-{task}-final"
        )
        if (
            manifest.get("project") != project
            or manifest.get("task_id") != task
            or manifest.get("repository") != job["repository"]
            or manifest.get("final_worktree") != str(expected_final)
            or not isinstance(manifest.get("developer_reports"), list)
            or len(manifest["developer_reports"]) != 1
            or manifest["developer_reports"][0].get("assignment_id") != "backend-main"
        ):
            raise Held(
                "Developer handoff identity or path differs from fixed V1 assignment"
            )
        self.copy(manifest_path, base / project / task / "qa-input.json", "alfred", ())
        for report in manifest["developer_reports"]:
            name = "report-" + report["assignment_id"] + ".json"
            self.copy(
                source / project / task / name,
                base / project / task / name,
                "alfred",
                (),
            )
        self.copy(
            source / f"request-{project}-{task}.json",
            base / f"request-{project}-{task}.json",
            "alfred",
            (),
        )
        self.copy(Path(self.p["registry"]), base / "registry.json", "alfred", ())
        plan = Path(self.p["gateway_state"]) / "cto-plans" / f"{project}-{task}.json"
        self.copy(plan, base / "gateway" / "cto-plans" / plan.name, "alfred", ())
        for kind in (
            "grant",
            "challenge",
            "decision",
            "issuance",
            "execution",
            "execution-result",
        ):
            name = f"{kind}-{job['grant_reference']}.json"
            self.copy(
                Path(self.p["grant_root"]) / name, base / "grants" / name, "alfred", ()
            )
        cfg = json.loads(
            Path(
                self.p.get(
                    "qa_config",
                    "/opt/alfred-independent-qa-v1/independent_qa/config.json",
                )
            ).read_bytes()
        )
        if cfg.get("model", {}).get("enabled") is not True:
            raise Held("Independent QA model is disabled")
        # Preserve both existing project checks; bind each fresh canonical
        # criterion to the approved unittest suite, rather than old fixture text.
        profile = cfg["projects"][project]
        if "python_unittest" not in profile["checks"]:
            raise Held("approved unittest profile missing")
        criteria = json.loads(plan.read_bytes())["acceptance_criteria"].splitlines()
        profile["criteria"] = [
            {"contains": c.removeprefix("- [ ] ").strip(), "check": "python_unittest"}
            for c in criteria
            if c.strip()
        ]
        self.freeze_json(base / "config.json", cfg)
        self.share(base, ("alfredqa",))
        # Only the activated disposable project and this task's worktrees gain
        # read access. No other project/grant store is exposed to QA.
        self.share(Path(job["repository"]), ("alfredqa",))
        self.share(
            Path(self.p["worktree_root"]) / f"fresh-{project}-{task}", ("alfredqa",)
        )
        self.directory(root / "qa-output", "alfredqa")
        result = self.worker(job, "qa", "alfredqa")
        if result.get("qa_model") is None:
            raise Held("independent QA model evidence missing")
        return result

    def clone(self, source, destination, *, bare=False):
        with tempfile.TemporaryDirectory(prefix="alfred-handoff-git-") as name:
            cfg = Path(name) / "gitconfig"
            cfg.write_text(
                "[safe]\n\tdirectory = " + json.dumps(str(source.resolve())) + "\n"
            )
            cfg.chmod(0o600)
            command(
                [
                    "/usr/bin/git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "clone",
                    "--no-local",
                    *(["--bare"] if bare else []),
                    str(source),
                    str(destination),
                ],
                env={
                    "PATH": "/usr/bin:/bin",
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": str(cfg),
                },
            )

    def reviewer(self, job):
        root = self.jobdir(job)
        base = root / "reviewer-input"
        self.directory(base)
        qa = root / "qa-output" / job["project"] / job["task_id"]
        for name in ("qa-report.json", "reviewer-handoff.json"):
            self.copy(qa / name, base / name, "alfredqa", ())
        qain = root / "qa-input"
        self.freeze(
            base / "cto-plan.json",
            (
                qain / "gateway/cto-plans" / f"{job['project']}-{job['task_id']}.json"
            ).read_bytes(),
        )
        self.freeze(
            base / "grant.json",
            (qain / "grants" / f"grant-{job['grant_reference']}.json").read_bytes(),
        )
        self.copy(Path(job["spec_path"]), base / "spec.md", "alfred", ())
        manifest = json.loads(
            (qain / job["project"] / job["task_id"] / "qa-input.json").read_bytes()
        )
        self.clone(Path(manifest["final_worktree"]), base / "snapshot")
        cfg = json.loads(
            Path(
                self.p.get(
                    "reviewer_config",
                    "/opt/alfred-reviewer-v1/independent_reviewer/config.json",
                )
            ).read_bytes()
        )
        cfg.update(
            project=job["project"],
            task_id=job["task_id"],
            expected_qa_report_sha256=hashlib.sha256(
                (base / "qa-report.json").read_bytes()
            ).hexdigest(),
        )
        self.freeze_json(base / "config.json", cfg)
        self.share(base, ("alfredreview",))
        self.directory(root / "reviewer-output", "alfredreview")
        return self.worker(job, "reviewer", "alfredreview")

    def publication_plan(self, job):
        root = self.jobdir(job)
        base = root / "publisher-input"
        self.directory(base)
        review = root / "reviewer-output" / job["project"] / job["task_id"]
        for name in ("review-report.json", "publication-handoff.json"):
            self.copy(review / name, base / name, "alfredreview", ())
        previous = root / "reviewer-input"
        for name in (
            "qa-report.json",
            "reviewer-handoff.json",
            "cto-plan.json",
            "grant.json",
            "spec.md",
        ):
            self.freeze(base / name, (previous / name).read_bytes())
        self.freeze(
            base / "registry.json", (root / "qa-input/registry.json").read_bytes()
        )
        qa = json.loads((base / "qa-report.json").read_bytes())
        # Clone the verified final worktree's common repository once. Cloning
        # the Reviewer clone again loses Developer sibling branches/objects
        # that Publisher independently verifies against the final tree.
        manifest = json.loads(
            (
                root / "qa-input" / job["project"] / job["task_id"] / "qa-input.json"
            ).read_bytes()
        )
        self.clone(Path(manifest["final_worktree"]), base / "source.git", bare=True)
        cfg = {
            "schema": "alfred.draft-pr-config/1",
            "project": job["project"],
            "task_id": job["task_id"],
            "final_revision": qa["final_revision"],
            **{
                k + "_sha256": hashlib.sha256(
                    (base / (filename + ".json")).read_bytes()
                ).hexdigest()
                for k, filename in (
                    ("review_report", "review-report"),
                    ("publication_handoff", "publication-handoff"),
                    ("qa_report", "qa-report"),
                )
            },
        }
        self.freeze_json(base / "config.json", cfg)
        self.share(base, ("alfredpublish",))
        self.directory(root / "publisher-output", "alfredpublish")
        result = self.worker(job, "prepare", "alfredpublish")
        raw = read_owned(
            root
            / "publisher-output"
            / job["project"]
            / job["task_id"]
            / "publication-plan.json",
            self.uids["alfredpublish"],
        )
        plan = json.loads(raw)
        if (
            plan["project"] != job["project"]
            or plan["task_id"] != job["task_id"]
            or plan["final_revision"] != qa["final_revision"]
            or plan["base_branch"] != self.p["base_branch"]
            or hashlib.sha256(raw).hexdigest() != result["publication_plan_sha256"]
            or plan["baseline_revision"] != job["baseline_revision"]
            or plan["destination"] != self.p["destination"]
        ):
            raise Held(
                "prepared publication differs from approved baseline/destination"
            )
        pub = root / "publication"
        self.directory(pub)
        self.freeze(pub / "approved-plan.json", raw, ("alfred",))
        self.freeze_json(pub / "seal.json", result, ("alfred",))
        self.share(pub, ("alfred",))
        return result

    def publication_challenge(self, job):
        raw = (self.jobdir(job) / "publication/approved-plan.json").read_bytes()
        return self.intake(
            {
                "op": "stage_publication_approval",
                "plan_raw": raw.decode(),
                "space_id": job["space_id"],
            }
        )

    def publication_authorization(self, job, reference):
        if not (
            Path(self.p["grant_root"]) / f"publication-decision-{reference}.json"
        ).exists():
            return None
        result = self.intake(
            {"op": "prepare_publication_authorization", "reference": reference}
        )
        record = result["authorization"]
        plan_path = self.jobdir(job) / "publication/approved-plan.json"
        plan = json.loads(plan_path.read_bytes())
        if (
            record.get("publication_plan_sha256")
            != hashlib.sha256(plan_path.read_bytes()).hexdigest()
            or not record.get("owner_event_id")
            or any(
                record.get(k) != plan[k]
                for k in (
                    "project",
                    "task_id",
                    "destination",
                    "base_branch",
                    "publication_branch",
                    "final_revision",
                )
            )
        ):
            raise Held("verified publication authorization differs from sealed plan")
        path = plan_path.with_name("authorization.json")
        if path.exists():
            if json.loads(path.read_bytes()) != record:
                raise Held("authorization conflict")
        else:
            self.freeze_json(path, record, ("alfredpublish",))
            self.share(path.parent, ("alfredpublish",))
        return {"path": str(path)}

    def publish(self, job):
        return self.worker(job, "publish", "alfredpublish")

    def completion(self, job):
        root = self.jobdir(job)
        base = root / "completion"
        self.directory(base)
        result = (
            root
            / "publisher-output"
            / job["project"]
            / job["task_id"]
            / "publication-result.json"
        )
        self.copy(result, base / "publication-result.json", "alfredpublish", ())
        self.freeze(
            base / "publication-plan.json",
            (root / "publication/approved-plan.json").read_bytes(),
        )
        self.freeze(
            base / "owner-authorization.json",
            (root / "publication/authorization.json").read_bytes(),
        )
        plan = json.loads((base / "publication-plan.json").read_bytes())
        cfg = {
            "schema": "alfred.completion-config/1",
            "enabled": True,
            "binding": {
                k: plan[k]
                for k in (
                    "project",
                    "task_id",
                    "destination",
                    "base_branch",
                    "publication_branch",
                    "final_revision",
                )
            },
            "owner_space_id": job["space_id"],
            "owner_sender_id": job["owner_id"],
            "owner_github_login": self.p["destination"].split("/")[0],
            "owner_merge_attested": False,
            "state_directory": self.p["completion_state"],
            **{
                name + "-sha256": hashlib.sha256(
                    (base / (name + ".json")).read_bytes()
                ).hexdigest()
                for name in (
                    "publication-plan",
                    "publication-result",
                    "owner-authorization",
                )
            },
        }
        self.freeze_json(base / "config.json", cfg)
        self.share(base, ("alfred",))
        # Deliberately no initialize(): retain T-0002's sent/uncertain guard forever.
        return self.worker(job, "completion", "alfred")


def require_root():
    if os.geteuid() != 0:
        raise PermissionError("existing privileged timer required")


def root_directory(root):
    info = root.lstat()
    if info.st_uid != 0 or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022:
        raise ValueError("unprotected handoff root")


def poll(policy_path=POLICY):
    require_root()
    policy, _ = protected_json(policy_path)
    if (
        policy.get("schema") != "alfred.fresh-v1-policy/1"
        or policy.get("enabled") is not True
    ):
        return {"state": "disabled"}
    if (Path(policy["gateway_state"]) / "PAUSE").exists() or (
        Path(policy["gateway_state"]) / "STOP"
    ).exists():
        return {"state": "paused"}
    if policy["specialists"] != ["backend"] or not 0 < policy["total_cost_limit"] <= 6:
        raise ValueError("unsupported V1 activation policy")
    host = Host(policy, policy_path)
    root = Path(policy["jobs"])
    root_directory(root)
    fd = os.open(root / ".poll.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Only native-confirmed new requests have these route records. Historical
        # T-0001/T-0002 without this record are never adopted or modified.
        journal = Path(policy["gateway_state"]) / "journal.jsonl"
        held_challenge = False
        held_failure = None
        for line in read_owned(journal, host.uids["alfred"]).splitlines():
            row = json.loads(line)
            if (
                row.get("kind") != "outcome"
                or row.get("outcome") != "filed"
                or row.get("project") != policy["project"]
            ):
                continue
            project, task = identity(row["project"], row["task_id"])
            if (
                re.fullmatch(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                    row["request_id"],
                )
                is None
            ):
                raise Held("invalid canonical request identifier")
            route_path = (
                Path(policy["grant_root"]) / f"request-route-{row['request_id']}.json"
            )
            if not route_path.exists():
                continue
            route = json.loads(read_owned(route_path, host.uids["alfred"]))
            intake_config = json.loads(
                read_owned(
                    Path(policy["gateway_state"]) / "v1-1-intake.json",
                    host.uids["alfred"],
                )
            )
            if (
                route.get("schema") != "alfred.confirmed-request-route/1"
                or route.get("project") != project
                or route.get("request_id") != row["request_id"]
                or route.get("owner_id") != intake_config["owner_sender_id"]
                or route.get("sidecar_uid") != pwd.getpwnam("alfredphoton").pw_uid
                or route.get("confirmation_event_id") == route.get("request_event_id")
                or not route.get("space_id")
                or not route.get("confirmation_event_id")
                or not route.get("native_reply_target")
            ):
                raise Held("canonical route evidence mismatch")
            directory = root / project / task
            if not directory.exists():
                if not directory.parent.exists():
                    host.directory(directory.parent)
                host.directory(directory)
                job = {
                    "project": project,
                    "task_id": task,
                    "request_id": row["request_id"],
                    "owner_id": route["owner_id"],
                    "space_id": route["space_id"],
                }
                host.freeze_json(directory / "job.json", job, USERS)
            else:
                job, _ = protected_json(directory / "job.json")
            if (directory / "complete.json").exists():
                continue
            if ((directory / "development-challenge.attempt.json").exists()
                    and not (directory / "development-challenge.result.json").exists()):
                # Never revisit an uncertain send. It must not starve a later
                # genuine owner request; no old evidence is modified/adopted.
                held_challenge = True
                continue
            failed = sorted(directory.glob("*.failure.json"))
            if failed:
                # A worker reported a definite failure and the stage is held for
                # good. Like the uncertain send above, never revisit it and never
                # let it starve a later genuine owner request; nothing is modified.
                held_failure = held_failure or failed[0].name.removesuffix(
                    ".failure.json"
                )
                continue
            result = advance(directory, job, host)
            if result["state"] == "complete":
                write_once(directory / "complete.json", result)
            return result  # One bounded fresh task per existing timer tick.
        if held_failure:
            return {"state": "held", "reason": held_failure + ": recorded failure; task held"}
        return ({"state": "held", "reason": "development-challenge: previous attempt requires reconciliation"}
                if held_challenge else {"state": "idle"})
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=POLICY)
    args = parser.parse_args()
    print(json.dumps(poll(args.policy)))


if __name__ == "__main__":
    main()
