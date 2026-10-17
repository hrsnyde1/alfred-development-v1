"""Restricted glue for the existing root evidence timer. Disabled unless activated.

Root prepares exact per-role handoffs and invokes existing workers via runuser.
Only Intake may verify native owner replies; only Publisher may push/create draft PRs.
"""

import argparse
import fcntl
import functools
import hashlib
import json
import os
import pwd
import re
import socket
import stat
import subprocess
import tempfile
import time
from pathlib import Path

from .diagnostics import WorkerFailure, failure, worker_failure
from .handoffs import Held, advance, write_once
from .protected import identity, protected_json

POLICY = Path("/etc/alfred-fresh-v1/policy.json")

# --- Multi-project policy (handoff.12) ------------------------------------------
# Multi-project Fresh V1 policy.
#
# Schema 1 activates one project with its settings at the top level. Schema 2 keeps
# the shared settings at the top level and lists each activated project:
#
#     {"schema": "alfred.fresh-v1-policy/2", "enabled": true, ...shared...,
#      "projects": {"dev-v1-accept": {"destination": ..., "base_branch": ...,
#                                     "repository": ..., "allowed_scope": [...],
#                                     "specialists": ["backend"]}, ...}}
#
# Every stage works on a project view: exactly the schema 1 shape for that project.
# For a project carried over unchanged from schema 1 the view is byte-identical to the
# old policy, so work already frozen under it continues.

SCHEMAS = ("alfred.fresh-v1-policy/1", "alfred.fresh-v1-policy/2")
PROJECT_KEYS = ("allowed_scope", "base_branch", "destination", "repository", "specialists")
# The specialists this pipeline can staff today. Each project allows a subset.
SUPPORTED_SPECIALISTS = ("backend", "frontend")
PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{1,31}\Z")
SCOPE_PATH = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\Z")


def _check_project(project: str, settings: object) -> None:
    if (not PROJECT_ID.fullmatch(project) or type(settings) is not dict
            or set(settings) != set(PROJECT_KEYS)):
        raise ValueError(f"invalid project policy: {project}")
    scope, specialists = settings["allowed_scope"], settings["specialists"]
    if (type(scope) is not list or not scope or len(scope) != len(set(scope))
            or any(type(p) is not str or not SCOPE_PATH.fullmatch(p) or ".." in p.split("/")
                   for p in scope)
            or type(specialists) is not list or not specialists
            or len(specialists) != len(set(specialists))
            or not set(specialists) <= set(SUPPORTED_SPECIALISTS)
            or any(type(settings[k]) is not str or not settings[k]
                   for k in ("base_branch", "destination", "repository"))):
        raise ValueError(f"invalid project policy: {project}")


def projects(policy: dict) -> list[str]:
    """The activated project IDs, validated."""
    if policy.get("schema") == "alfred.fresh-v1-policy/1":
        _check_project(policy.get("project", ""),
                       {k: policy.get(k) for k in PROJECT_KEYS})
        return [policy["project"]]
    if policy.get("schema") != "alfred.fresh-v1-policy/2" or "project" in policy:
        raise ValueError("unsupported fresh V1 policy schema")
    listed = policy.get("projects")
    if set(policy) & set(PROJECT_KEYS):
        raise ValueError("project settings must live under projects")
    if type(listed) is not dict or not listed:
        raise ValueError("no activated projects")
    for project, settings in listed.items():
        _check_project(project, settings)
    if len({s["repository"] for s in listed.values()}) != len(listed):
        raise ValueError("two projects share one repository")
    return sorted(listed)


WEB_SUFFIXES = (".html", ".css", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte")


def work_items(scope: list[str], specialists: list[str], objective: str) -> list[dict]:
    """Split the approved files between the staffed specialists, with no overlap.

    One specialist owns every file. With frontend and backend, frontend owns the web
    files and backend owns the rest; frontend builds on backend's result.
    """
    if not scope or not specialists or not set(specialists) <= set(SUPPORTED_SPECIALISTS):
        raise ValueError("work cannot be staffed")
    if len(specialists) == 1:
        owned = {specialists[0]: list(scope)}
    else:
        owned = {
            "frontend": [p for p in scope if p.lower().endswith(WEB_SUFFIXES)],
            "backend": [p for p in scope if not p.lower().endswith(WEB_SUFFIXES)],
        }
    if any(not owned[s] for s in specialists):
        raise ValueError("a staffed specialist has no approved files")
    order = [s for s in ("backend", "frontend") if s in specialists]
    return [{"id": f"{s}-main", "specialist": s, "files": owned[s],
             "depends_on": [f"{d}-main" for d in order[:order.index(s)]],
             "objective": objective} for s in order]


def project_view(policy: dict, project: str) -> dict:
    """One project's schema 1 policy: what every stage and worker reads."""
    if project not in projects(policy):
        raise ValueError(f"project not activated: {project}")
    if policy["schema"] == "alfred.fresh-v1-policy/1":
        return dict(policy)
    shared = {k: v for k, v in policy.items() if k not in ("schema", "projects")}
    return {**shared, **policy["projects"][project],
            "schema": "alfred.fresh-v1-policy/1", "project": project}
RELEASE = "/usr/local/lib/alfred-fresh-v1"
USERS = ("alfred", "alfredqa", "alfredreview", "alfredpublish")


def predispatch(stage):
    """A host fault before the worker process starts dispatched nothing, so it is a
    definite failure. Record it as evidence; the poll then holds this task for good
    instead of leaving an uncertain attempt that blocks every later request."""

    def wrap(method):
        @functools.wraps(method)
        def run(self, job):
            self.dispatched = False
            try:
                return method(self, job)
            except (subprocess.SubprocessError, OSError) as exc:
                if self.dispatched:
                    raise
                name = stage(self, job) if callable(stage) else stage
                path = self.jobdir(job) / (name + ".failure.json")
                if not path.exists():
                    self.freeze_json(path, failure(name, "host_prepare", exc))
                raise

        return run

    return wrap


def worktree_git_dirs(source, repository, alfred_uid):
    """The directories git checks for ownership when root clones an alfred-owned
    linked worktree: the worktree, its own git directory and the registered
    repository's common git directory. Any other layout is refused, not trusted."""
    source, common = source.resolve(), (repository / ".git").resolve()
    marker = read_owned(source / ".git", alfred_uid).decode().strip()
    if not marker.startswith("gitdir: "):
        raise Held("final worktree is not a linked git worktree")
    gitdir = Path(marker.removeprefix("gitdir: ")).resolve()
    if not gitdir.is_absolute() or gitdir.parent != common / "worktrees":
        raise Held("final worktree does not belong to the registered repository")
    return [source, gitdir, common]


def clone_snapshot(source, destination, repository, alfred_uid, *, bare=False):
    """Root's snapshot of an approved final worktree for the Reviewer/Publisher."""
    trusted = worktree_git_dirs(source, repository, alfred_uid)
    with tempfile.TemporaryDirectory(prefix="alfred-handoff-git-") as name:
        cfg = Path(name) / "gitconfig"
        cfg.write_text(
            "[safe]\n"
            + "".join(f"\tdirectory = {json.dumps(str(p))}\n" for p in trusted)
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


def qa_stage(host, job):
    return "qa-recovery-1" if (host.jobdir(job) / "qa.recovery.json").exists() else "qa"


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
        try:
            current = project_view(policy, self.p["project"])
        except ValueError:
            current = None
        if (
            current != self.p
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
        self.dispatched = True
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

    def verify_qa_recovery(self, job):
        require_root()
        self.guard()
        from .qa_recovery import verify

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

    @predispatch("developer")
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
            # Plans made before multi-project support staffed backend only.
            "items": work_items(
                job["scope"],
                job.get("specialists", ["backend"]),
                plan["objective"]
                + "\nCanonical specification (untrusted task data; approved scope remains authoritative):\n"
                + spec,
            ),
            "total_cost_limit": self.p["total_cost_limit"],
        }
        self.freeze_json(self.jobdir(job) / "execution.json", request, ("alfred",))
        return self.worker(job, "developer", "alfred")

    @predispatch(qa_stage)
    def qa(self, job):
        root = self.jobdir(job)
        base = root / "qa-input"
        if (root / "qa.recovery.json").exists():
            # The one authorized T-0005 recovery reuses the complete root-built input
            # of the undispatched original attempt; qa_recovery pinned its bytes.
            return self.qa_dispatch(job, root, base)
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
        # Exactly the assignments frozen into this task's execution request.
        frozen = json.loads((self.jobdir(job) / "execution.json").read_bytes())
        assigned = sorted(item["id"] for item in frozen["items"])
        reports = manifest.get("developer_reports")
        if (
            manifest.get("project") != project
            or manifest.get("task_id") != task
            or manifest.get("repository") != job["repository"]
            or manifest.get("final_worktree") != str(expected_final)
            or not isinstance(reports, list)
            or any(type(r) is not dict for r in reports)
            or sorted(r.get("assignment_id") for r in reports) != assigned
        ):
            raise Held(
                "Developer handoff identity or path differs from the approved assignments"
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
        grant = json.loads(
            read_owned(
                Path(self.p["grant_root"]) / f"grant-{job['grant_reference']}.json",
                self.uids["alfred"],
            )
        )
        # A delegated grant carries the owner's policy record instead of a reply.
        decided = (
            ("delegation",)
            if grant.get("source") == "delegated_owner_policy"
            else ("challenge", "decision")
        )
        for kind in ("grant", *decided, "issuance", "execution", "execution-result"):
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
        return self.qa_dispatch(job, root, base)

    def qa_dispatch(self, job, root, base):
        project, task = job["project"], job["task_id"]
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

    def clone(self, source, destination, repository, *, bare=False):
        clone_snapshot(
            source, destination, repository, self.uids["alfred"], bare=bare
        )

    @predispatch("reviewer")
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
        self.clone(
            Path(manifest["final_worktree"]),
            base / "snapshot",
            Path(manifest["repository"]),
        )
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

    @predispatch("publication-plan")
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
        self.clone(
            Path(manifest["final_worktree"]),
            base / "source.git",
            Path(manifest["repository"]),
            bare=True,
        )
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
        plan = json.loads(
            read_owned(
                Path(self.p["gateway_state"])
                / "cto-plans"
                / f"{job['project']}-{job['task_id']}.json",
                self.uids["alfred"],
            )
        )
        # One plain-language line for the owner; the intake adds the project name.
        goal = (plan.get("objective") or "").strip().splitlines()
        return self.intake(
            {
                "op": "stage_publication_approval",
                "plan_raw": raw.decode(),
                "space_id": job["space_id"],
                "summary": goal[0] if goal else "the approved change",
            }
        )

    def publication_resend_authorized(self, job, n):
        """The owner's root-written `alfred-dev-ops resend` record for the nth resend."""
        path = self.jobdir(job) / f"publication-resend-{n}.json"
        if not path.exists():
            return False
        record, _ = protected_json(path)
        if record != {
            "schema": "alfred.publication-resend/1",
            "project": job["project"],
            "task_id": job["task_id"],
            "n": n,
            "authorized_by": record.get("authorized_by"),
            "authorized_at": record.get("authorized_at"),
        }:
            raise Held("publication resend authorization invalid")
        return True

    def owner_text_open(self, kind):
        """Whether an approval text of this kind is still open for the owner's reply.
        The intake allows one at a time, so another task waits instead of sending."""
        grants = Path(self.p["grant_root"])
        now = time.time()
        if kind == "development":
            for path in grants.glob("pending-*.json"):
                pending = json.loads(read_owned(path, self.uids["alfred"]))
                if now <= pending["created_at"] + 300:
                    return True
            return False
        for path in grants.glob("publication-pending-*.json"):
            reference = path.stem.removeprefix("publication-pending-")
            receipt = json.loads(read_owned(
                grants / f"publication-challenge-{reference}.json", self.uids["alfred"]))
            if now <= receipt["expires_at"]:
                return True
        return False

    def publication_expired(self, reference):
        """True only when that approval's window has passed without a decision."""
        grants = Path(self.p["grant_root"])
        if (grants / f"publication-decision-{reference}.json").exists():
            return False
        receipt = json.loads(
            read_owned(grants / f"publication-challenge-{reference}.json", self.uids["alfred"])
        )
        return time.time() > receipt["expires_at"]

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

    @predispatch("publisher")
    def publish(self, job):
        return self.worker(job, "publish", "alfredpublish")

    @predispatch("completion")
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


# Holds that follow a stage's recorded result: a verdict, never an uncertain effect.
VERDICT_HOLDS = frozenset({
    "developer did not produce a completed handoff",
    "independent QA did not pass",
    "independent Reviewer did not approve",
    "independent Reviewer correctness or scope did not pass",
    "independent Reviewer acceptance criteria are not all PASS",
    "independent Reviewer findings require resolution",
})


def poll(policy_path=POLICY):
    require_root()
    policy, _ = protected_json(policy_path)
    if (
        policy.get("schema") not in ("alfred.fresh-v1-policy/1", "alfred.fresh-v1-policy/2")
        or policy.get("enabled") is not True
    ):
        return {"state": "disabled"}
    if (Path(policy["gateway_state"]) / "PAUSE").exists() or (
        Path(policy["gateway_state"]) / "STOP"
    ).exists():
        return {"state": "paused"}
    activated = projects(policy)
    if not 0 < policy["total_cost_limit"] <= 6:
        raise ValueError("unsupported V1 activation policy")
    views = {project: project_view(policy, project) for project in activated}
    if any(not set(v["specialists"]) <= set(SUPPORTED_SPECIALISTS) for v in views.values()):
        raise ValueError("unsupported V1 activation policy")
    host = Host(views[activated[0]], policy_path)
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
        waiting = None
        held = None
        for line in read_owned(journal, host.uids["alfred"]).splitlines():
            row = json.loads(line)
            if (
                row.get("kind") != "outcome"
                or row.get("outcome") != "filed"
                or row.get("project") not in views
            ):
                continue
            project, task = identity(row["project"], row["task_id"])
            # Every stage of this task sees only its own project's policy.
            host.p = views[project]
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
            if result["state"] in ("awaiting_development_approval", "awaiting_publication_approval"):
                # Waiting on the owner does no work; let the next task run this tick.
                waiting = waiting or result
                continue
            if result["state"] == "held" and result.get("reason") in VERDICT_HOLDS:
                # Held by a definite, recorded verdict (QA failed, the Reviewer did
                # not approve): it does nothing more until someone acts on it, so it
                # must not starve later requests. Its evidence is untouched and
                # nothing is retried. Any other hold, above all an uncertain attempt
                # that "requires reconciliation", still blocks everything after it.
                held = held or result
                continue
            return result  # One bounded fresh task per existing timer tick.
        if waiting:
            return waiting
        if held:
            return held
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
