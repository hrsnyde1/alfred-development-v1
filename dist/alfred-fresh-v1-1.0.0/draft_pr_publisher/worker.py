"""Evidence-bound, on-demand GitHub Draft PR publisher.

Preparation is read-only. Publication requires a separate root-owned owner
authorization record. Only Git push and create-draft-PR are write operations.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from urllib import error, parse, request

import yaml

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
TASK = re.compile(r"T-[0-9]{4,}\Z")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*\Z")
GENERAL_REVIEW_CRITERION = "Correctness, maintainability, security, and approved scope."


class PublicationError(Exception):
    def __init__(self, requirement: str, detail: str):
        super().__init__(detail)
        self.requirement = requirement
        self.detail = detail


def require(ok: bool, requirement: str, detail: str) -> None:
    if not ok:
        raise PublicationError(requirement, detail)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def read_json(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise PublicationError("input", f"Cannot read valid JSON at {path}: {exc}") from exc
    require(type(data) is dict, "input", f"JSON object required at {path}")
    return data, sha(raw)


def safe_path(name: str) -> bool:
    return bool(type(name) is str and name and not name.startswith("/") and
                "\\" not in name and all(part not in {"", ".", ".."} for part in name.split("/")))


def git(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.devnull}
    try:
        proc = subprocess.run(["/usr/bin/git", "-c", f"safe.directory={repo}", "-C", str(repo), *args],
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublicationError("git", f"Git inspection unavailable: {type(exc).__name__}") from exc
    require(proc.returncode == 0, "git", f"Git inspection failed: {args[0]}")
    return proc.stdout if binary else proc.stdout.decode("utf-8", "replace").strip()


def registry_destination(path: Path, project: str) -> tuple[str, str, str]:
    try:
        data = yaml.safe_load(path.read_bytes())
    except (OSError, yaml.YAMLError) as exc:
        raise PublicationError("registry", f"Canonical registry unavailable: {type(exc).__name__}") from exc
    require(type(data) is dict and data.get("version") == 1 and type(data.get("projects")) is list,
            "registry", "Invalid canonical project registry")
    entries = [row for row in data["projects"] if type(row) is dict and row.get("id") == project]
    require(len(entries) == 1 and entries[0].get("status") == "active", "registry",
            "Project is absent, ambiguous, or inactive")
    destination = entries[0].get("repo")
    require(type(destination) is dict, "registry", "Registered repository is missing")
    github, base = destination.get("github"), destination.get("default_branch")
    require(type(github) is str and REPO.fullmatch(github) is not None and
            type(base) is str and BRANCH.fullmatch(base) is not None and
            ".." not in base and not base.endswith("/"),
            "registry", "Registered GitHub destination or base branch is invalid")
    local = entries[0].get("local_path")
    require(type(local) is str and bool(local), "registry", "Registered local repository is missing")
    return github, base, local


def verify_git(repo: Path, baseline: str, revision: str, commits: list[str],
               hashes: dict[str, str], scope: set[str]) -> str:
    require(repo.is_absolute() and repo.is_dir(), "source", "Absolute read-only source snapshot required")
    require(git(repo, "cat-file", "-t", baseline) == "commit" and
            git(repo, "cat-file", "-t", revision) == "commit", "revision", "Missing Git commit")
    require(git(repo, "merge-base", baseline, revision) == baseline and
            git(repo, "rev-parse", f"{revision}^{{tree}}") ==
            git(repo, "rev-parse", f"{commits[0]}^{{tree}}"),
            "revision", "Final revision is not the approved Developer tree")
    raw = git(repo, "diff", "--no-ext-diff", "--name-status", "-z", baseline, revision, binary=True)
    pieces = raw.split(b"\0")
    require(pieces[-1] == b"" and (len(pieces) - 1) % 2 == 0, "scope", "Malformed Git diff")
    changed = {}
    for i in range(0, len(pieces) - 1, 2):
        status, path = pieces[i].decode("utf-8", "replace"), pieces[i + 1].decode("utf-8", "replace")
        require(status in {"M", "A"} and safe_path(path) and path not in changed,
                "scope", "Unsupported or ambiguous Git change")
        changed[path] = status
    require(set(changed) == set(hashes) and set(changed) <= scope,
            "scope", "Git diff differs from approved changed files")
    for commit in git(repo, "rev-list", f"{baseline}..{revision}").splitlines():
        touched = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z",
                      commit, binary=True).split(b"\0")
        require(touched[-1] == b"" and all(path.decode("utf-8", "replace") in scope
                                             for path in touched[:-1]),
                "scope", "Intermediate commit touches a file outside owner-approved scope")
    for path, expected in hashes.items():
        require(sha(git(repo, "show", f"{revision}:{path}", binary=True)) == expected,
                "hash", f"Git blob hash mismatch: {path}")
    diff = git(repo, "diff", "--no-ext-diff", "--no-textconv", "--binary",
               baseline, revision, "--", binary=True)
    require(len(diff) <= 262144, "scope", "Diff exceeds V1 publication bound")
    return sha(diff)


def verify_inputs(*, config_path: Path, registry_path: Path, handoff_path: Path,
                  review_path: Path, qa_path: Path, qa_handoff_path: Path,
                  plan_path: Path, grant_path: Path, spec_path: Path,
                  source_repo: Path) -> dict:
    config, _ = read_json(config_path)
    require(config.get("schema") == "alfred.draft-pr-config/1", "config", "Invalid publisher config")
    project, task, revision = (config.get(k) for k in ("project", "task_id", "final_revision"))
    require(type(project) is str and IDENT.fullmatch(project) is not None and
            type(task) is str and TASK.fullmatch(task) is not None and
            type(revision) is str and HEX40.fullmatch(revision) is not None,
            "config", "Invalid pinned project, task, or revision")
    for key in ("review_report_sha256", "publication_handoff_sha256", "qa_report_sha256"):
        require(type(config.get(key)) is str and HEX64.fullmatch(config[key]) is not None,
                "config", f"Missing {key} pin")
    destination, base, registered_local = registry_destination(registry_path, project)
    handoff, handoff_sha = read_json(handoff_path)
    review, review_sha = read_json(review_path)
    qa, qa_sha = read_json(qa_path)
    qa_handoff, qa_handoff_sha = read_json(qa_handoff_path)
    require(handoff_sha == config["publication_handoff_sha256"] and
            review_sha == config["review_report_sha256"] and
            qa_sha == config["qa_report_sha256"], "digest", "Pinned evidence digest mismatch")
    handoff_keys = {"schema", "project", "task_id", "developer_commits", "final_revision",
                    "changed_file_hashes", "qa_report_sha256", "review_report_sha256",
                    "decision", "next_stage"}
    require(set(handoff) == handoff_keys and handoff.get("schema") == "alfred.publication-handoff/1" and
            handoff.get("decision") == "APPROVED" and handoff.get("next_stage") == "github_draft_pr_preparation",
            "review", "Malformed or non-APPROVED publication handoff")
    require(review.get("schema") == "alfred.review-report/1" and
            review.get("decision") == "APPROVED" and review.get("correctness") == "PASS" and
            review.get("scope") == "PASS" and review.get("next_authorized_stage") == "github_draft_pr_preparation" and
            handoff.get("review_report_sha256") == review_sha,
            "review", "Review is not an internally consistent APPROVED decision")
    require(qa.get("schema") == "alfred.qa-report/1" and qa.get("decision") == "PASS" and
            qa.get("next_authorized_action") == "independent_reviewer" and
            qa_handoff.get("schema") == "alfred.reviewer-handoff/1" and
            qa_handoff.get("decision") == "PASS" and
            qa_handoff.get("next_stage") == "independent_reviewer" and
            qa_handoff.get("qa_report_sha256") == qa_sha and
            review.get("qa_report_sha256") == qa_sha and
            review.get("reviewer_handoff_sha256") == qa_handoff_sha and
            handoff.get("qa_report_sha256") == qa_sha,
            "qa", "QA PASS or digest chain mismatch")
    keys = ("project", "task_id", "final_revision", "developer_commits", "changed_file_hashes")
    require(all(handoff.get(k) == review.get(k) for k in keys) and
            all(handoff.get(k) == qa.get(k) for k in keys) and
            all(qa_handoff.get(k) == qa.get(k) for k in keys) and
            all(handoff.get(k) == (task if k == "task_id" else project if k == "project" else revision)
                for k in ("task_id", "project", "final_revision")),
            "identity", "Project, task, revision, commit, or file hashes disagree")
    baseline = qa.get("baseline_revision")
    commits, hashes = handoff.get("developer_commits"), handoff.get("changed_file_hashes")
    require(type(baseline) is str and HEX40.fullmatch(baseline) is not None and
            review.get("baseline_revision") == baseline and qa_handoff.get("baseline_revision") == baseline and
            type(commits) is list and len(commits) == 1 and type(commits[0]) is str and
            HEX40.fullmatch(commits[0]) is not None and type(hashes) is dict and bool(hashes) and
            all(safe_path(p) and type(h) is str and HEX64.fullmatch(h) for p, h in hashes.items()),
            "identity", "Malformed baseline, Developer commit, or changed-file hashes")
    require(type(qa.get("tests")) is list and qa["tests"] and
            all(type(t) is dict and t.get("result") == "PASS" and t.get("exit_code") == 0
                for t in qa["tests"]) and
            type(qa.get("acceptance_criteria")) is list and qa["acceptance_criteria"] and
            all(type(row) is dict and row.get("result") == "PASS" for row in qa["acceptance_criteria"]),
            "qa", "QA tests or acceptance criteria are not all PASS")
    expected = [row.get("criterion") for row in qa["acceptance_criteria"]]
    coverage = review.get("acceptance_coverage")
    require(type(coverage) is list and len(coverage) >= len(expected) and
            len(expected) == len(set(expected)) and
            all(type(row) is dict and row.get("result") == "PASS" for row in coverage) and
            all(sum(row.get("criterion") == criterion for row in coverage) == 1 for criterion in expected) and
            (len(coverage) == len(expected) or
             (len(coverage) == len(expected) + 1 and
              sum(row.get("criterion") == GENERAL_REVIEW_CRITERION for row in coverage) == 1)),
            "coverage", "Reviewer omitted or failed an original acceptance criterion")
    evidence = qa.get("evidence")
    require(type(evidence) is dict, "authority", "QA authority evidence absent")
    plan, plan_sha = read_json(plan_path)
    grant, grant_sha = read_json(grant_path)
    try:
        spec_sha = sha(spec_path.read_bytes())
    except OSError as exc:
        raise PublicationError("authority", f"Task specification unavailable: {type(exc).__name__}") from exc
    require(plan_sha == evidence.get("cto_plan_sha256") and
            grant_sha == evidence.get("development_grant_sha256") and
            spec_sha == evidence.get("canonical_task_sha256"),
            "authority", "CTO plan, grant, or task specification digest mismatch")
    require(plan.get("schema") == "alfred.cto-plan/1" and plan.get("project") == project and
            plan.get("task_id") == task and plan.get("spec_sha256") == spec_sha and
            plan.get("repository") == registered_local and
            grant.get("schema") == "alfred.development-grant/1" and
            grant.get("state") == "approved" and grant.get("project") == project and
            grant.get("task_id") == task and grant.get("plan_sha256") == plan_sha and
            grant.get("spec_sha256") == spec_sha and
            grant.get("repository") == registered_local and
            grant.get("reference") == evidence.get("development_grant_reference"),
            "authority", "Canonical CTO plan or owner development grant mismatch")
    criteria = [line.removeprefix("- [ ] ").strip() for line in plan.get("acceptance_criteria", "").splitlines()
                if line.startswith("- [ ] ")]
    require(criteria and len(criteria) == len(expected) and set(criteria) == set(expected),
            "coverage", "QA criteria do not match approved CTO criteria")
    scope = grant.get("scope")
    require(type(scope) is list and scope and all(safe_path(p) and p in plan.get("scope", "")
                                                  for p in scope) and set(hashes) <= set(scope),
            "scope", "Changed files exceed owner-approved scope")
    diff_sha = verify_git(source_repo, baseline, revision, commits, hashes, set(scope))
    require(review.get("diff_sha256") == diff_sha, "diff", "Reviewer inspected a different Git diff")
    branch = f"alfred/{project}/{task}-{revision[:12]}"
    return {"schema": "alfred.draft-pr-plan/1", "project": project, "task_id": task,
            "destination": destination, "base_branch": base, "publication_branch": branch,
            "baseline_revision": baseline, "final_revision": revision,
            "developer_commits": commits, "changed_file_hashes": hashes,
            "diff_sha256": diff_sha, "qa_report_sha256": qa_sha,
            "review_report_sha256": review_sha, "publication_handoff_sha256": handoff_sha,
            "cto_plan_sha256": plan_sha, "development_grant_sha256": grant_sha,
            "task_spec_sha256": spec_sha, "status": "READY_FOR_OWNER_AUTHORIZATION"}


def write_same_or_new(path: Path, value: dict) -> str:
    raw = canonical(value)
    if path.exists():
        require(path.read_bytes() == raw, "duplicate", f"Conflicting existing record: {path.name}")
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
    return sha(raw)


def prepare(*, output_root: Path, **evidence_paths: Path) -> tuple[dict, str]:
    plan = verify_inputs(**evidence_paths)
    target = output_root / plan["project"] / plan["task_id"]
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (target / ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        plan_sha = write_same_or_new(target / "publication-plan.json", plan)
    return plan, plan_sha


def verify_authorization(path: Path, plan: dict, plan_sha: str,
                         *, trusted_uid: int = 0, trusted_root: Path = Path("/")) -> dict:
    # The owner reply is authenticated out of band by the trusted administrator.
    # This root-owned exact-bound record is the narrow publication capability.
    require(path.is_absolute() and trusted_root.is_absolute() and
            (path == trusted_root or trusted_root in path.parents),
            "owner_authorization", "Authorization is outside the trusted root")
    current = path
    while True:
        try:
            meta = current.lstat()
        except OSError as exc:
            raise PublicationError("owner_authorization",
                                   f"Protected authorization path unavailable: {type(exc).__name__}") from exc
        require(not stat.S_ISLNK(meta.st_mode) and meta.st_uid == trusted_uid and
                not (meta.st_mode & 0o022), "owner_authorization",
                "Authorization path is not protected by the trusted administrator")
        if current == trusted_root:
            break
        current = current.parent
    authorization, _ = read_json(path)
    require(set(authorization) == {"schema", "decision", "project", "task_id", "destination",
                                   "base_branch", "publication_branch", "final_revision",
                                   "publication_plan_sha256", "owner_event_id", "purpose"} and
            authorization.get("schema") == "alfred.github-draft-pr-authorization/1" and
            authorization.get("decision") == "approved" and
            authorization.get("purpose") == "one_github_draft_pr" and
            type(authorization.get("owner_event_id")) is str and
            bool(authorization["owner_event_id"].strip()) and
            authorization.get("publication_plan_sha256") == plan_sha and
            all(authorization.get(k) == plan[k] for k in
                ("project", "task_id", "destination", "base_branch", "publication_branch", "final_revision")),
            "owner_authorization", "Explicit owner authorization is missing or not bound to this plan")
    return authorization


class GitHub:
    def __init__(self, token_file: Path):
        try:
            metadata = token_file.stat()
            require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.geteuid() and
                    not (metadata.st_mode & 0o077), "credential",
                    "Dedicated token file must be publisher-owned mode 0600")
            token = token_file.read_text().strip()
        except OSError as exc:
            raise PublicationError("credential", f"Dedicated token file unavailable: {type(exc).__name__}") from exc
        require(bool(token) and "\n" not in token and "\r" not in token,
                "credential", "Dedicated GitHub token is unavailable")
        self.token = token

    def api(self, method: str, path: str, payload: dict | None = None, *, missing_ok: bool = False):
        body = json.dumps(payload).encode() if payload is not None else None
        req = request.Request("https://api.github.com" + path, data=body, method=method,
                              headers={"Accept": "application/vnd.github+json",
                                       "Authorization": f"Bearer {self.token}",
                                       "Content-Type": "application/json",
                                       "User-Agent": "alfred-draft-pr-publisher-v1"})
        try:
            with request.urlopen(req, timeout=15) as response:
                return json.loads(response.read(1048576))
        except error.HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise PublicationError("github", f"GitHub {method} request failed: HTTP {exc.code}") from exc
        except (OSError, ValueError) as exc:
            raise PublicationError("github", f"GitHub {method} request failed: {type(exc).__name__}") from exc

    def repository(self, destination: str):
        return self.api("GET", f"/repos/{destination}")

    def ref(self, destination: str, branch: str):
        return self.api("GET", f"/repos/{destination}/git/ref/heads/{parse.quote(branch, safe='/')}",
                        missing_ok=True)

    def prs(self, destination: str, owner: str, branch: str, base: str):
        query = parse.urlencode({"state": "all", "head": f"{owner}:{branch}", "base": base,
                                 "per_page": 100})
        return self.api("GET", f"/repos/{destination}/pulls?{query}")

    def create_draft(self, destination: str, payload: dict):
        require(payload.get("draft") is True, "draft", "Only draft PR creation is permitted")
        return self.api("POST", f"/repos/{destination}/pulls", payload)


def push_branch(source_repo: Path, plan: dict, token_file: Path,
                *, _fixture_remote: str | None = None) -> None:
    with tempfile.TemporaryDirectory(prefix="alfred-publish-") as name:
        temp = Path(name)
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": str(Path(__file__).with_name("askpass.py")),
               "ALFRED_PUBLISH_TOKEN_FILE": str(token_file)}
        # Local fetch starts upload-pack in the root-owned, read-only source.
        # Command-line -c settings do not reach that child. Give only fetch a
        # private temporary config containing the exact approved source path.
        source_path = str(source_repo.resolve())
        require(not source_path.endswith("/*"), "push", "Source trust must name one repository")
        safe_config = temp / "source-safe.gitconfig"
        try:
            safe_config.write_text('[safe]\n\tdirectory = ' +
                                   json.dumps(source_path, ensure_ascii=False) + '\n')
            safe_config.chmod(0o600)
        except OSError as exc:
            raise PublicationError("push", "Isolated Git fetch configuration unavailable") from exc
        fetch_env = {**env, "GIT_CONFIG_GLOBAL": str(safe_config)}
        # A fresh bare repository cannot carry unapproved worktree files.
        commands = [
            ["/usr/bin/git", "init", "--bare", "-q", str(temp)],
            ["/usr/bin/git", "-C", str(temp), "fetch", "--no-tags", str(source_repo),
             plan["baseline_revision"], plan["final_revision"]],
            ["/usr/bin/git", "-C", str(temp), "push", "--porcelain",
             _fixture_remote or f"https://github.com/{plan['destination']}.git",
             f"{plan['final_revision']}:refs/heads/{plan['publication_branch']}"]]
        for index, command in enumerate(commands):
            try:
                result = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL,
                                        timeout=60 if index == 2 else 20,
                                        env=fetch_env if index == 1 else env)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise PublicationError("push", f"Isolated Git operation failed: {type(exc).__name__}") from exc
            require(result.returncode == 0, "push", "Isolated Git operation failed")


def validate_pr(pr: dict, plan: dict, plan_sha: str) -> str:
    require(type(pr) is dict and pr.get("draft") is True and pr.get("state") == "open" and
            type(pr.get("head")) is dict and pr["head"].get("sha") == plan["final_revision"] and
            pr["head"].get("ref") == plan["publication_branch"] and
            pr["head"].get("repo", {}).get("full_name") == plan["destination"] and
            type(pr.get("base")) is dict and pr["base"].get("ref") == plan["base_branch"] and
            pr["base"].get("sha") == plan["baseline_revision"] and
            pr["base"].get("repo", {}).get("full_name") == plan["destination"] and
            type(pr.get("body")) is str and
            plan_sha in pr["body"] and
            plan["qa_report_sha256"] in pr["body"] and
            plan["review_report_sha256"] in pr["body"] and
            type(pr.get("number")) is int and pr["number"] > 0 and
            pr.get("html_url") == f"https://github.com/{plan['destination']}/pull/{pr['number']}",
            "draft", "GitHub PR is not an open draft at the approved revision")
    return pr["html_url"]


def result_record(plan: dict, plan_sha: str, status: str, *, url: str | None = None,
                  detail: str | None = None) -> dict:
    return {"schema": "alfred.draft-pr-result/1", "project": plan["project"],
            "task_id": plan["task_id"], "destination": plan["destination"],
            "base_branch": plan["base_branch"], "publication_branch": plan["publication_branch"],
            "commit": plan["final_revision"], "publication_plan_sha256": plan_sha,
            "qa_report_sha256": plan["qa_report_sha256"],
            "review_report_sha256": plan["review_report_sha256"],
            "draft_pr_url": url, "status": status, "detail": detail,
            "next_stage": "alfred_completion_notification" if status == "PUBLISHED_DRAFT" else
                          "publication_investigation"}


def publish(*, output_root: Path, authorization_path: Path, token_file: Path,
            github: GitHub | None = None, pusher=push_branch,
            trusted_uid: int = 0, trusted_root: Path = Path("/"),
            **evidence_paths: Path) -> dict:
    plan = verify_inputs(**evidence_paths)
    target = output_root / plan["project"] / plan["task_id"]
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (target / ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        plan_sha = write_same_or_new(target / "publication-plan.json", plan)
        verify_authorization(authorization_path, plan, plan_sha,
                             trusted_uid=trusted_uid, trusted_root=trusted_root)
        final = target / "publication-result.json"
        if final.exists():
            previous, _ = read_json(final)
            require(previous.get("publication_plan_sha256") == plan_sha, "duplicate",
                    "Existing publication result belongs to another plan")
            if previous.get("status") == "PUBLISHED_DRAFT":
                return previous
        try:
            service = github if github is not None else GitHub(token_file)
            remote = service.repository(plan["destination"])
            require(type(remote) is dict and remote.get("full_name") == plan["destination"] and
                    remote.get("default_branch") == plan["base_branch"],
                    "destination", "GitHub repository does not match canonical registry")
            base = service.ref(plan["destination"], plan["base_branch"])
            require(type(base) is dict and base.get("object", {}).get("sha") == plan["baseline_revision"],
                    "baseline", "Registered GitHub base branch is not the approved baseline")
            branch = service.ref(plan["destination"], plan["publication_branch"])
            if branch is not None:
                require(branch.get("object", {}).get("sha") == plan["final_revision"],
                        "duplicate", "Publication branch exists at a different revision")
            owner = plan["destination"].split("/", 1)[0]
            prs = service.prs(plan["destination"], owner, plan["publication_branch"], plan["base_branch"])
            require(type(prs) is list and len(prs) <= 1, "duplicate", "Ambiguous existing pull requests")
            if prs:
                require(branch is not None, "duplicate", "Pull request has no expected branch")
                url = validate_pr(prs[0], plan, plan_sha)
            else:
                if branch is None:
                    pusher(evidence_paths["source_repo"], plan, token_file)
                body = (f"Alfred task {plan['task_id']} ({plan['project']}).\n\n"
                        f"Approved commit: `{plan['final_revision']}`\n"
                        f"QA report SHA-256: `{plan['qa_report_sha256']}`\n"
                        f"Reviewer report SHA-256: `{plan['review_report_sha256']}`\n"
                        f"Publication plan SHA-256: `{plan_sha}`\n\n"
                        "Draft for owner review. No merge or deployment is authorized.\n")
                created = service.create_draft(plan["destination"],
                    {"title": f"{plan['task_id']}: approved development change",
                     "head": plan["publication_branch"], "base": plan["base_branch"],
                     "body": body, "draft": True, "maintainer_can_modify": False})
                url = validate_pr(created, plan, plan_sha)
            result = result_record(plan, plan_sha, "PUBLISHED_DRAFT", url=url)
        except PublicationError as exc:
            result = result_record(plan, plan_sha, "ERROR", detail=f"{exc.requirement}: {exc.detail}")
        raw = canonical(result)
        temporary = target / "publication-result.json.tmp"
        with temporary.open("wb") as stream:
            stream.write(raw)
        os.replace(temporary, final)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "publish"))
    for flag in ("config", "registry", "handoff", "review", "qa", "qa_handoff", "plan",
                 "grant", "spec", "source_repo", "output_root"):
        parser.add_argument("--" + flag.replace("_", "-"), required=True, type=Path)
    parser.add_argument("--authorization", type=Path)
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args(argv)
    paths = {"config_path": args.config, "registry_path": args.registry,
             "handoff_path": args.handoff, "review_path": args.review, "qa_path": args.qa,
             "qa_handoff_path": args.qa_handoff, "plan_path": args.plan,
             "grant_path": args.grant, "spec_path": args.spec, "source_repo": args.source_repo}
    try:
        if args.mode == "prepare":
            result, digest = prepare(output_root=args.output_root, **paths)
            print(json.dumps({"status": result["status"], "destination": result["destination"],
                              "branch": result["publication_branch"], "plan_sha256": digest}))
        else:
            require(args.authorization is not None and args.token_file is not None,
                    "owner_authorization", "Publish requires authorization and dedicated token file")
            result = publish(output_root=args.output_root, authorization_path=args.authorization,
                             token_file=args.token_file, **paths)
            print(json.dumps(result, sort_keys=True))
            return 0 if result["status"] == "PUBLISHED_DRAFT" else 2
    except PublicationError as exc:
        print(json.dumps({"status": "BLOCKED", "requirement": exc.requirement,
                          "detail": exc.detail}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
