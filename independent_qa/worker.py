"""Verify Developer evidence and execute independent, bounded QA checks.

The input is untrusted. Only canonical Gateway files and Git object data establish
scope and code identity. This module never writes to a repository or grant store.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import resource
import selectors
import signal
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

import yaml

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IDENT = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
TASK = re.compile(r"T-[0-9]{4,}\Z")
MAX_INPUT = 131072
MAX_FILE = 262144
MAX_TREE = 2097152
CALCULATOR_EXAMPLES = (
    "import calculator; assert calculator.add(7, 3) == 10; "
    "assert calculator.subtract(7, 3) == 4; print('add=10 subtract=4')"
)
CHECKS = {
    "calculator_examples": ["/usr/bin/python3", "-B", "-c", CALCULATOR_EXAMPLES],
    "python_unittest": ["/usr/bin/python3", "-B", "-m", "unittest", "discover", "-v"],
    "python_pytest": ["/usr/bin/python3", "-B", "-m", "pytest", "-q"],
    "node_test": ["/usr/bin/node", "--test"],
}


class QAFailure(Exception):
    def __init__(self, requirement: str, detail: str, *, blocked: bool = False):
        super().__init__(detail)
        self.requirement, self.detail, self.blocked = requirement, detail, blocked


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_INPUT:
            raise ValueError("oversized JSON")
        def unique(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError("duplicate JSON key")
                out[key] = value
            return out
        obj = json.loads(raw, object_pairs_hook=unique)
        if type(obj) is not dict:
            raise ValueError("JSON root is not an object")
        return obj, digest(raw)
    except (OSError, UnicodeError, ValueError) as exc:
        raise QAFailure("handoff_structure", f"Cannot read valid {path.name}: {type(exc).__name__}") from exc


def require(ok: bool, requirement: str, detail: str) -> None:
    if not ok:
        raise QAFailure(requirement, detail)


def git(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["/usr/bin/git", "-c", f"safe.directory={repo}", "-C", str(repo), *args], capture_output=True,
                            timeout=12, check=False, env={"PATH": "/usr/bin:/bin", "GIT_NO_REPLACE_OBJECTS": "1"})
    if result.returncode:
        raise QAFailure("git_evidence", f"Git {args[0]} failed for {repo.name}")
    return result.stdout if binary else result.stdout.decode("utf-8", "strict").strip()


def safe_path(value: str) -> bool:
    if type(value) is not str or not value or "\\" in value or "\0" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and all(part not in ("", ".", "..") for part in value.split("/")) and path.parts[0] != ".git"


def same_repo(repo: Path, worktree: Path) -> bool:
    if not worktree.is_dir() or worktree.is_symlink():
        return False
    try:
        return (repo / git(repo, "rev-parse", "--git-common-dir")).resolve() == (
            worktree / git(worktree, "rev-parse", "--git-common-dir")).resolve()
    except QAFailure:
        return False


def tree_files(worktree: Path, revision: str) -> dict[str, bytes]:
    rows = git(worktree, "ls-tree", "-rz", "--full-tree", revision, binary=True).split(b"\0")
    files, total = {}, 0
    for row in rows:
        if not row:
            continue
        try:
            meta, raw_path = row.split(b"\t", 1)
            mode, kind, obj = meta.decode("ascii").split(" ")
            path = raw_path.decode("utf-8", "strict")
        except (ValueError, UnicodeError) as exc:
            raise QAFailure("git_evidence", "Invalid Git tree entry") from exc
        require(mode in {"100644", "100755"} and kind == "blob" and safe_path(path),
                "source_inventory", f"Unsupported tracked path: {path}")
        content = git(worktree, "cat-file", "blob", obj, binary=True)
        total += len(content)
        require(len(content) <= MAX_FILE and total <= MAX_TREE,
                "source_inventory", "Git tree exceeds QA snapshot bounds")
        files[path] = content
    return files


def changed_paths(worktree: Path, baseline: str, revision: str) -> list[str]:
    raw = git(worktree, "diff", "--name-status", "-z", baseline, revision, binary=True)
    entries = raw.split(b"\0")
    paths = []
    index = 0
    while index < len(entries) and entries[index]:
        status = entries[index].decode("ascii", "strict")
        require(status == "M", "changed_files", f"Unsupported Git change: {status}")
        path = entries[index + 1].decode("utf-8", "strict")
        require(safe_path(path), "changed_files", "Unsafe changed path")
        paths.append(path)
        index += 2
    return sorted(paths)


def load_authority(registry_path: Path, gateway_state: Path, grant_root: Path,
                   developer_state: Path,
                   project: str, task_id: str, repository: Path) -> tuple[dict, dict, dict, str, str, str]:
    registry = yaml.safe_load(registry_path.read_text())
    projects = [p for p in registry.get("projects", []) if p.get("id") == project]
    require(len(projects) == 1, "canonical_project", "Project missing or duplicated in Gateway registry")
    require(Path(projects[0]["local_path"]).resolve() == repository.resolve(),
            "canonical_project", "Repository differs from Gateway registry")
    specs = list((repository / ".dev/tasks").glob(f"{task_id}-*.md"))
    require(len(specs) == 1, "canonical_task", "Canonical task missing or ambiguous")
    spec_bytes = specs[0].read_bytes()
    spec_text = spec_bytes.decode("utf-8", "strict")
    require(re.search(rf"(?m)^id: {re.escape(task_id)}$", spec_text) is not None and
            re.search(rf"(?m)^project: {re.escape(project)}$", spec_text) is not None,
            "canonical_task", "Task front matter identity mismatch")
    plan_path = gateway_state / "cto-plans" / f"{project}-{task_id}.json"
    plan, plan_sha = read_json(plan_path)
    require(plan.get("schema") == "alfred.cto-plan/1" and plan.get("project") == project and
            plan.get("task_id") == task_id and plan.get("repository") == str(repository) and
            plan.get("spec_sha256") == digest(spec_bytes) and not plan.get("clarification_required"),
            "approved_plan", "CTO plan does not bind canonical task and repository")
    request, _ = read_json(developer_state / f"request-{project}-{task_id}.json")
    ref = request.get("authorization_reference")
    require(request.get("schema") == "alfred.developer-run-request/1" and
            request.get("project") == project and request.get("task_id") == task_id and
            type(ref) is str and re.fullmatch(r"[0-9a-f]{32}", ref) and
            request.get("scope") and type(request["scope"]) is list,
            "owner_approval", "Developer run request does not bind task and grant")
    grant, grant_sha = read_json(grant_root / f"grant-{ref}.json")
    issuance, _ = read_json(grant_root / f"issuance-{ref}.json")
    claim, claim_sha = read_json(grant_root / f"execution-{ref}.json")
    result, _ = read_json(grant_root / f"execution-result-{ref}.json")
    expected_request = {"schema": "alfred.development-approval-request/1", "project": project,
                        "task_id": task_id, "repository": str(repository),
                        "spec_sha256": digest(spec_bytes), "plan_sha256": plan_sha,
                        "scope": grant.get("scope"), "specialists": grant.get("specialists"),
                        "worktree_root": grant.get("worktree_root"), "state": "pending_owner_decision"}
    if grant.get("source") == "delegated_owner_policy":
        decided = delegated_decision(grant_root, ref, grant, grant_sha, issuance, expected_request)
    else:
        decided = owner_reply_decision(grant_root, ref, grant, grant_sha, issuance, expected_request)
    require(grant.get("schema") == "alfred.development-grant/1" and grant.get("state") == "approved" and
            grant.get("reference") == ref and grant.get("issuer") == "trusted_owner_authority" and
            grant.get("repository") == str(repository) and
            grant.get("spec_sha256") == digest(spec_bytes) and grant.get("plan_sha256") == plan_sha and
            grant.get("scope") == request.get("scope") and
            grant.get("worktree_root") == request.get("worktree_root") and decided and
            claim.get("grant_sha256") == grant_sha and claim.get("reference") == ref and
            result.get("claim_sha256") == claim_sha and result.get("reference") == ref and
            result.get("status") == "completed",
            "owner_approval", "Grant issuance or completed execution evidence mismatch")
    return plan, grant, projects[0], plan_sha, digest(spec_bytes), grant_sha


def owner_reply_decision(grant_root: Path, ref: str, grant: dict, grant_sha: str,
                         issuance: dict, expected_request: dict) -> bool:
    """The owner's native in-thread iMessage reply approved this exact request."""
    challenge, challenge_sha = read_json(grant_root / f"challenge-{ref}.json")
    decision, decision_sha = read_json(grant_root / f"decision-{ref}.json")
    checks = {"authenticated_sender", "same_dm", "fresh_event", "native_direct_reply",
              "not_forwarded", "within_challenge_lifetime", "exact_phrase", "single_use"}
    return (challenge.get("schema") == "alfred.development-challenge/1" and
            challenge.get("request") == expected_request and challenge.get("reference") == ref and
            decision.get("schema") == "alfred.development-owner-decision/1" and
            decision.get("reference") == ref and decision.get("challenge_sha256") == challenge_sha and
            decision.get("sender_id") == challenge.get("owner_id") and
            decision.get("space_id") == challenge.get("space_id") and
            decision.get("native_reply_target") == challenge.get("message_id") and
            decision.get("content_sha256") == challenge.get("phrase_sha256") and
            decision.get("owner_event_id") == grant.get("owner_event_id") and
            decision.get("direction") == "inbound" and decision.get("is_forward") is False and
            decision.get("content_type") == "text" and
            type(decision.get("checks")) is dict and set(decision["checks"]) == checks and
            all(decision["checks"].values()) and
            issuance.get("grant_sha256") == grant_sha and
            issuance.get("challenge_sha256") == challenge_sha and
            issuance.get("decision_sha256") == decision_sha)


def delegated_decision(grant_root: Path, ref: str, grant: dict, grant_sha: str,
                       issuance: dict, expected_request: dict) -> bool:
    """The owner's root-protected standing policy approved this exact request."""
    record, record_sha = read_json(grant_root / f"delegation-{ref}.json")
    policy = record.get("policy")
    development = policy.get("development_approval") if type(policy) is dict else None
    policy_sha = digest(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode())
    return (record.get("schema") == "alfred.development-delegated-decision/1" and
            record.get("reference") == ref and record.get("request") == expected_request and
            record.get("decision") == "approve_development" and
            record.get("decided_by") == "owner_delegation_policy" and
            type(policy) is dict and record.get("policy_sha256") == policy_sha and
            policy.get("schema") == "alfred.development-delegation-policy/1" and
            # "delegated": the owner's request "yes" also covers its draft PR (handoff.29).
            policy.get("publication_approval") in ("owner", "delegated") and
            # "delegated": the pipeline also squash-merges after QA and review (handoff.31).
            policy.get("merge_approval", "owner") in ("owner", "delegated") and
            set(policy) - {"merge_approval"} == {"schema", "development_approval",
                                                 "publication_approval"} and
            type(development) is dict and development.get("enabled") is True and
            type(development.get("projects")) is list and
            expected_request["project"] in development["projects"] and
            grant.get("delegation_sha256") == record_sha and
            issuance.get("schema") == "alfred.development-delegated-issuance/1" and
            issuance.get("grant_sha256") == grant_sha and
            issuance.get("delegation_sha256") == record_sha and
            issuance.get("policy_sha256") == policy_sha)


def verify(manifest_path: Path, report_dir: Path, registry: Path, gateway_state: Path,
           grant_root: Path) -> dict:
    manifest, manifest_sha = read_json(manifest_path)
    project, task = manifest.get("project"), manifest.get("task_id")
    require(type(project) is str and IDENT.fullmatch(project) and type(task) is str and TASK.fullmatch(task),
            "handoff_structure", "Invalid project or task identity")
    require(manifest_path.name == "qa-input.json" and manifest_path.parent.name == task and
            manifest_path.parent.parent.name == project, "handoff_structure", "Handoff path identity mismatch")
    required = {"schema", "project", "task_id", "repository", "developer_reports", "final_worktree",
                "final_revision", "changed_file_hashes", "state"}
    require(set(manifest) == required and manifest["schema"] == "alfred.qa-input/1" and
            manifest["state"] == "ready_for_independent_qa" and
            type(manifest["developer_reports"]) is list and manifest["developer_reports"],
            "handoff_structure", "Malformed QA input")
    repo = Path(manifest["repository"])
    final = Path(manifest["final_worktree"])
    require(repo.is_absolute() and final.is_absolute(),
            "git_evidence", "Repository or final worktree path is not absolute")
    plan, grant, _, plan_sha, spec_sha, grant_sha = load_authority(
        registry, gateway_state, grant_root, manifest_path.parent.parent.parent, project, task, repo)
    approved = set(grant.get("scope", []))
    require(approved and all(safe_path(p) for p in approved) and
            all(p in plan.get("scope", "") for p in approved),
            "approved_scope", "Grant scope is outside CTO plan")
    require(final.parent.resolve() == Path(grant["worktree_root"]).resolve() and
            final.resolve() != repo.resolve(),
            "git_evidence", "Final snapshot is outside authorized worktree root")
    require(same_repo(repo, final),
            "git_evidence", "Final worktree does not belong to registered repository")
    final_rev = manifest["final_revision"]
    require(type(final_rev) is str and HEX40.fullmatch(final_rev) and git(final, "rev-parse", "HEAD") == final_rev and
            not git(final, "status", "--porcelain", "--untracked-files=all"),
            "final_revision", "Final worktree revision or cleanliness mismatch")
    hashes = manifest["changed_file_hashes"]
    require(type(hashes) is dict and hashes and all(safe_path(p) and type(h) is str and HEX64.fullmatch(h)
                                                       for p, h in hashes.items()),
            "changed_file_hashes", "Malformed changed-file hashes")
    baseline, commits, report_refs, assignment_ids = None, [], {}, []
    for report in manifest["developer_reports"]:
        require(type(report) is dict and report.get("schema") == "alfred.developer-report/1" and
                report.get("project") == project and report.get("task_id") == task and
                report.get("repository") == str(repo) and report.get("status") == "completed" and
                type(report.get("assignment_id")) is str and report.get("specialist") in grant.get("specialists", []) and
                type(report.get("tests")) is list and report["tests"] and
                type(report.get("files_modified")) is list and report["files_modified"] and
                report.get("qa_handoff", {}).get("ready") is True,
                "developer_report", "Developer report structure or identity mismatch")
        assignment = report["assignment_id"]
        assignment_ids.append(assignment)
        on_disk = report_dir / f"report-{assignment}.json"
        stored, report_sha = read_json(on_disk)
        require(stored == report, "developer_report", "QA input embeds a different Developer report")
        report_refs[assignment] = {"path": str(on_disk), "sha256": report_sha}
        developer_tree = Path(report["worktree"])
        require(developer_tree.parent.resolve() == Path(grant["worktree_root"]).resolve() and
                developer_tree.resolve() != repo.resolve(),
                "developer_commit", "Developer worktree is outside authorized root")
        require(same_repo(repo, developer_tree) and not git(developer_tree, "status", "--porcelain", "--untracked-files=all"),
                "developer_commit", "Developer worktree is invalid or dirty")
        revs = report.get("commits")
        require(type(revs) is list and revs and all(type(c) is str and HEX40.fullmatch(c) for c in revs) and
                git(developer_tree, "rev-parse", "HEAD") == revs[0],
                "developer_commit", "Developer commit mismatch")
        base = report.get("baseline_revision")
        require(type(base) is str and HEX40.fullmatch(base) and
                git(developer_tree, "merge-base", base, revs[0]) == base and
                git(developer_tree, "rev-list", f"{base}..{revs[0]}").splitlines() == revs,
                "git_baseline", "Developer commit chain does not start at baseline")
        baseline = baseline or base
        require(baseline == base and report.get("assigned_scope") == sorted(set(report.get("assigned_scope", []))) and
                set(report["assigned_scope"]) <= approved,
                "approved_scope", "Assignment baseline or scope mismatch")
        modified = changed_paths(developer_tree, base, revs[0])
        declared = {r.get("path"): r.get("sha256") for r in report["files_modified"] if type(r) is dict}
        # The assignment bounds what may change; a request rarely needs every file
        # (dark mode leaves the API alone). At least one change, none outside it.
        require(modified and set(modified) == set(declared) and
                set(modified) <= set(report["assigned_scope"]),
                "changed_files", "Actual Developer changes differ from assignment")
        for p in modified:
            blob = git(developer_tree, "show", f"{revs[0]}:{p}", binary=True)
            require(digest(blob) == declared[p] == report["qa_handoff"]["changed_file_hashes"].get(p),
                    "changed_file_hashes", f"Developer file hash mismatch: {p}")
        require(report["qa_handoff"]["baseline_revision"] == base,
                "git_baseline", "Developer QA handoff baseline mismatch")
        commits.extend(revs)
    require(len(set(assignment_ids)) == len(assignment_ids), "handoff_structure", "Duplicate assignment")
    require(git(final, "merge-base", baseline, final_rev) == baseline,
            "git_baseline", "Final revision is outside baseline history")
    changed = changed_paths(final, baseline, final_rev)
    require(set(changed) == set(hashes) and set(changed) <= approved,
            "changed_files", "Final revision includes unauthorized or undeclared file changes")
    files = tree_files(final, final_rev)
    for path in changed:
        require(path in files and digest(files[path]) == hashes[path],
                "changed_file_hashes", f"Final file hash mismatch: {path}")
    expected = {row["path"]: row["sha256"] for rep in manifest["developer_reports"] for row in rep["files_modified"]}
    require(expected == hashes, "changed_file_hashes", "Final hashes differ from Developer handoff")
    if len(manifest["developer_reports"]) == 1:
        require(git(final, "rev-parse", f"{final_rev}^{{tree}}") ==
                git(final, "rev-parse", f"{commits[0]}^{{tree}}"),
                "final_revision", "Final revision tree differs from Developer commit")
    return {"project": project, "task": task, "repo": repo, "final": final,
            "baseline": baseline, "revision": final_rev, "commits": commits, "files": files,
            "changed": hashes, "plan": plan, "plan_sha": plan_sha, "spec_sha": spec_sha,
            "grant_reference": grant["reference"], "grant_sha": grant_sha,
            "manifest_sha": manifest_sha, "reports": report_refs, "assignments": assignment_ids}


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    # A low per-UID process limit can deny namespace creation before the
    # sandbox starts when the shared host UID already has other processes.
    resource.setrlimit(resource.RLIMIT_NPROC, (512, 512))


def bounded_process(args: list[str]) -> tuple[int, str]:
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True,
                            preexec_fn=_limits, env={"PATH": "/usr/bin:/bin"})
    output = bytearray()
    selector = selectors.DefaultSelector()
    assert proc.stdout is not None
    os.set_blocking(proc.stdout.fileno(), False)
    selector.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + 45
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, 45)
            for key, _ in selector.select(min(remaining, 0.25)):
                try:
                    chunk = os.read(key.fd, 65536)
                except BlockingIOError:
                    continue
                if chunk:
                    output.extend(chunk[:max(0, 16384 - len(output))])
                else:
                    selector.unregister(key.fd)
        proc.wait(timeout=max(0.1, deadline - time.monotonic()))
        return proc.returncode, output.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        raise
    finally:
        selector.close()
        proc.stdout.close()


def execute(files: dict[str, bytes], checks: list[str], *, bwrap: str = "/usr/bin/bwrap") -> list[dict]:
    if not Path(bwrap).is_file() or not os.access(bwrap, os.X_OK):
        raise QAFailure("execution_capability", "Bubblewrap executable unavailable", blocked=True)
    results = []
    with tempfile.TemporaryDirectory(prefix="alfred-independent-qa-") as tmp:
        root = Path(tmp)
        for path, content in files.items():
            dest = root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            dest.chmod(0o444)
        for check in checks:
            command = CHECKS[check]
            args = [bwrap, "--unshare-all", "--die-with-parent", "--ro-bind", "/usr", "/usr",
                    "--ro-bind", "/bin", "/bin", "--ro-bind", "/lib", "/lib",
                    "--ro-bind-try", "/lib64", "/lib64", "--dev", "/dev", "--proc", "/proc",
                    "--tmpfs", "/tmp", "--ro-bind", str(root), "/workspace", "--chdir", "/workspace",
                    "--clearenv", "--setenv", "HOME", "/tmp", "--setenv", "PATH", "/usr/bin:/bin",
                    "--setenv", "PYTHONDONTWRITEBYTECODE", "1", *command]
            try:
                exit_code, output = bounded_process(args)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise QAFailure("execution_capability", f"Isolated test execution unavailable: {type(exc).__name__}", blocked=True) from exc
            if exit_code and ("bwrap:" in output or "No permissions to create new namespace" in output):
                raise QAFailure("execution_capability", output.strip()[:300], blocked=True)
            results.append({"id": check, "command": command, "exit_code": exit_code,
                            "result": "PASS" if exit_code == 0 else "FAIL", "output": output})
    return results


def analyze_with_model(config: dict, context: dict) -> tuple[dict | None, list[dict]]:
    choice = config.get("model", {})
    if not choice.get("enabled"):
        return None, []
    if choice.get("provider") != "codex" or choice.get("model") not in {"gpt-6-sol", "gpt-6.1-sol"}:
        return None, [{"severity": "info", "requirement": "model_analysis", "detail": "Configured QA model unavailable"}]
    cli = Path.home() / ".local/bin/codex"
    if not cli.is_file():
        return None, [{"severity": "info", "requirement": "model_analysis", "detail": "Codex CLI unavailable"}]
    prompt = json.dumps({"task": "Analyze code diff for missing coverage and security issues. Return concise JSON with findings array; each item has severity, requirement, detail. No tools or code changes.",
                         "objective": context["plan"].get("objective"), "changed_files": list(context["changed"]),
                         "source": {p: context["files"][p].decode("utf-8", "replace") for p in context["changed"]}})
    with tempfile.TemporaryDirectory(prefix="alfred-qa-model-") as tmp:
        args = [str(cli), "exec", "--ignore-user-config", "--ignore-rules", "--disable", "shell_tool",
                "--disable", "unified_exec", "--disable", "browser_use", "--disable", "apps",
                "--disable", "code_mode_host", "--model", choice["model"], "--sandbox", "read-only",
                "--ephemeral", "--skip-git-repo-check", "--json", "-C", tmp,
                "-c", f'model_reasoning_effort="{choice.get("reasoning_effort", "medium")}"', prompt]
        try:
            proc = subprocess.run(args, capture_output=True, timeout=min(int(choice.get("timeout_seconds", 120)), 180),
                                  stdin=subprocess.DEVNULL, check=False)
            if proc.returncode:
                raise ValueError("model invocation failed")
            events = [json.loads(line) for line in proc.stdout.decode().splitlines() if line.startswith("{")]
            if not any(e.get("type") == "turn.completed" for e in events):
                raise ValueError("model did not complete")
            answers = [e["item"]["text"] for e in events if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"]
            answer = json.loads(answers[-1])
            findings = [f for f in answer.get("findings", []) if type(f) is dict and
                        f.get("severity") in {"critical", "high", "medium", "low", "info"} and
                        all(type(f.get(k)) is str for k in ("requirement", "detail"))][:12]
            return {"provider": "codex", "model": choice["model"], "reasoning_effort": choice.get("reasoning_effort", "medium")}, findings
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            return None, [{"severity": "info", "requirement": "model_analysis", "detail": "Optional model analysis unavailable"}]


def write_once(path: Path, data: dict) -> bytes:
    raw = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise QAFailure("duplicate_execution", f"Conflicting existing artifact: {path.name}", blocked=True)
        return raw
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return raw


def publish_contract(target: Path, report: dict, raw: bytes) -> None:
    if report["decision"] == "PASS":
        handoff = {"schema": "alfred.reviewer-handoff/1", "project": report["project"],
                   "task_id": report["task_id"], "final_revision": report["final_revision"],
                   "baseline_revision": report["baseline_revision"],
                   "developer_commits": report["developer_commits"],
                   "changed_file_hashes": report["changed_file_hashes"],
                   "qa_report_sha256": digest(raw), "decision": "PASS",
                   "next_stage": "independent_reviewer"}
        write_once(target / "reviewer-handoff.json", handoff)
    elif report["decision"] == "FAIL":
        assignments = list(report["evidence"].get("developer_reports", {}))
        correction = {"schema": "alfred.qa-correction-request/1", "project": report["project"],
                      "task_id": report["task_id"],
                      "assignment_id": assignments[0] if assignments else "unverified_assignment",
                      "developer_commit": report["developer_commits"][0] if report["developer_commits"] else "unverified",
                      "failed_revision": report["final_revision"],
                      "qa_report_sha256": digest(raw),
                      "requirements": [f["requirement"] + ": " + f["detail"]
                                       for f in report["findings"] if f["severity"] in {"critical", "high"}],
                      "next_stage": "responsible_developer",
                      "authorization": "new_owner_approval_required_before_code_change"}
        write_once(target / "correction-request.json", correction)


def run(manifest_path: Path, output_root: Path, registry: Path, gateway_state: Path,
        grant_root: Path, config_path: Path, *, bwrap: str = "/usr/bin/bwrap") -> dict:
    config, _ = read_json(config_path)
    require(config.get("schema") == "alfred.qa-config/1", "test_configuration", "Invalid QA config")
    project, task = manifest_path.parent.parent.name, manifest_path.parent.name
    require(IDENT.fullmatch(project) and TASK.fullmatch(task), "handoff_structure", "Invalid handoff path")
    profile = config.get("projects", {}).get(project, {})
    checks = profile.get("checks")
    require(type(checks) is list and checks and len(set(checks)) == len(checks) and all(c in CHECKS for c in checks),
            "test_configuration", "Project has no valid allowlisted checks")
    criteria_map = profile.get("criteria")
    require(type(criteria_map) is list and criteria_map and all(type(row) is dict and
            set(row) == {"contains", "check"} and type(row["contains"]) is str and row["contains"] and
            row["check"] in checks for row in criteria_map),
            "test_configuration", "Project acceptance mapping is invalid")
    target = output_root / project / task
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (target / ".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = target / "qa-report.json"
        if existing.exists():
            report, _ = read_json(existing)
            manifest_sha = digest(manifest_path.read_bytes()) if manifest_path.is_file() else None
            require(report.get("evidence", {}).get("qa_input_sha256") == manifest_sha,
                    "duplicate_execution", "Existing QA report belongs to a different input")
            publish_contract(target, report, existing.read_bytes())
            return report
        report = {"schema": "alfred.qa-report/1", "project": project, "task_id": task,
                  "decision": "BLOCKED", "developer_commits": [], "final_revision": None,
                  "baseline_revision": None, "files_inspected": [], "changed_file_hashes": {}, "tests": [],
                  "acceptance_criteria": [], "findings": [], "qa_model": None, "evidence": {},
                  "next_authorized_action": "resolve_qa_blocker"}
        if manifest_path.is_file():
            report["evidence"]["qa_input_sha256"] = digest(manifest_path.read_bytes())
            report["evidence"]["qa_input_path"] = str(manifest_path)
        context = None
        try:
            context = verify(manifest_path, manifest_path.parent, registry, gateway_state, grant_root)
            report.update({"developer_commits": context["commits"], "final_revision": context["revision"],
                           "baseline_revision": context["baseline"], "files_inspected": sorted(context["files"]),
                           "changed_file_hashes": context["changed"]})
            report["evidence"].update({"cto_plan_sha256": context["plan_sha"],
                "canonical_task_sha256": context["spec_sha"], "developer_reports": context["reports"],
                "development_grant_reference": context["grant_reference"],
                "development_grant_sha256": context["grant_sha"],
                "final_worktree": str(context["final"])})
            report["tests"] = execute(context["files"], checks, bwrap=bwrap)
            for test in report["tests"]:
                if test["result"] == "FAIL":
                    report["findings"].append({"severity": "high", "requirement": test["id"],
                                               "detail": f"Independent test exited {test['exit_code']}"})
            criteria = context["plan"].get("acceptance_criteria", "").splitlines()
            for line in criteria:
                criterion = line.removeprefix("- [ ] ").strip()
                if not criterion:
                    continue
                matches = [row["check"] for row in criteria_map if row["contains"] in criterion]
                check = matches[0] if len(matches) == 1 else None
                outcome = next((t["result"] for t in report["tests"] if t["id"] == check), "BLOCKED")
                report["acceptance_criteria"].append({"criterion": criterion, "result": outcome,
                                                     "evidence": check or "no configured check"})
            if not report["acceptance_criteria"]:
                raise QAFailure("acceptance_criteria", "CTO plan has no checkable acceptance criteria", blocked=True)
            if any(c["result"] == "BLOCKED" for c in report["acceptance_criteria"]):
                raise QAFailure("acceptance_criteria", "At least one CTO acceptance criterion lacks an independent check", blocked=True)
            model, model_findings = analyze_with_model(config, context)
            report["qa_model"] = model
            report["findings"].extend(model_findings)
            report["decision"] = "FAIL" if any(f["severity"] in {"critical", "high"} for f in report["findings"]) else "PASS"
        except QAFailure as exc:
            report["decision"] = "BLOCKED" if exc.blocked else "FAIL"
            report["findings"].append({"severity": "medium" if exc.blocked else "high",
                                       "requirement": exc.requirement, "detail": exc.detail})
        except (TypeError, KeyError, ValueError, OSError, UnicodeError) as exc:
            report["decision"] = "FAIL"
            report["findings"].append({"severity": "high", "requirement": "handoff_structure",
                                       "detail": f"Malformed QA evidence: {type(exc).__name__}"})
        report["next_authorized_action"] = ("independent_reviewer" if report["decision"] == "PASS"
                                            else "responsible_developer_after_owner_approval" if report["decision"] == "FAIL"
                                            else "resolve_qa_blocker")
        raw = write_once(existing, report)
        publish_contract(target, report, raw)
        return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qa-input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--gateway-state", type=Path, required=True)
    parser.add_argument("--grant-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    args = parser.parse_args()
    result = run(args.qa_input, args.output_root, args.registry, args.gateway_state, args.grant_root, args.config)
    print(json.dumps({"decision": result["decision"], "project": result["project"], "task_id": result["task_id"]}))
    raise SystemExit(0 if result["decision"] == "PASS" else 1)


if __name__ == "__main__":
    main()
