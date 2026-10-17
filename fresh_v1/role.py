"""Invoke installed V1 workers under their existing identities, with frozen inputs."""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from developer_v1.router import select_specialists
from fresh_v1.diagnostics import WorkerFailure, failure, planning_output
from fresh_v1.handoffs import write_once
from fresh_v1.protected import identity, protected_json

# Read-only view of the gateway directory inside the Evidence sandbox (drop-in
# BindReadOnlyPaths), searchable by role identities without traversing /home/alfred.
GATEWAY_VIEW = Path("/run/alfred-fresh-v1-gateway")


def git(repo, *args):
    return (
        planning_output(
            "git_fetch" if "fetch" in args else "git_ref_verify",
            ["/usr/bin/git", "-C", str(repo), "-c", "core.hooksPath=/dev/null", *args],
            env={
                **os.environ,
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0",
            },
            timeout=30,
        )
        .decode()
        .strip()
    )


def prepare_plan(job, policy, *, remote_main=None, fetch=True):
    """Existing CTO, canonical task and current remote main; no checkout/reset."""
    from alfred.gateway.dispatcher import gateway_lock
    from alfred.gateway.journal import Journal
    from alfred.registry.loader import parse_registry, read_registry_data

    from v1_cto import cto

    registry = parse_registry(read_registry_data(Path(policy["registry"])))
    row = [
        r
        for r in Journal(Path(policy["gateway_state"]) / "journal.jsonl").entries()
        if r.get("kind") == "outcome"
        and r.get("outcome") == "filed"
        and all(r.get(k) == job[k] for k in ("project", "task_id", "request_id"))
    ]
    if len(row) != 1:
        raise ValueError("no unique canonical filing")
    with gateway_lock(Path(policy["gateway_state"])):
        repo, spec, name, raw = cto._task_for(row[0], registry)
        project = registry.project(job["project"])
        if (
            str(repo) != policy["repository"]
            or project.repo.github != policy["destination"]
            or project.repo.default_branch != policy["base_branch"]
            or spec.get("risk") == "high"
        ):
            raise ValueError("project outside activated low-risk policy")
        if remote_main is None:
            remote_main = (
                planning_output(
                    "github_main_lookup",
                    [
                        "/usr/bin/gh",
                        "api",
                        "--hostname",
                        "github.com",
                        "--method",
                        "GET",
                        f"repos/{policy['destination']}/git/ref/heads/{policy['base_branch']}",
                        "--jq",
                        ".object.sha",
                    ],
                    timeout=20,
                )
                .decode()
                .strip()
            )
        import re

        if re.fullmatch(r"[0-9a-f]{40}", remote_main) is None:
            raise ValueError("registered main unavailable")
        if fetch:
            # Read-only GitHub fetch using the existing operator gh credential helper.
            git(
                repo,
                "-c",
                "credential.helper=",
                "-c",
                "credential.helper=!/usr/bin/gh auth git-credential",
                "fetch",
                "--no-tags",
                "--no-write-fetch-head",
                f"https://github.com/{policy['destination']}.git",
                f"refs/heads/{policy['base_branch']}:refs/remotes/alfred-v1/main",
            )
            if git(repo, "rev-parse", "refs/remotes/alfred-v1/main") != remote_main:
                raise ValueError("main moved during planning")
        with tempfile.TemporaryDirectory(prefix="alfred-cto-readback-") as directory:
            snapshot = Path(directory)
            rows = planning_output(
                "git_tree",
                ["/usr/bin/git", "-C", str(repo), "ls-tree", "-rz", remote_main],
                timeout=20,
            )
            total = 0
            for entry in rows.split(b"\0"):
                if not entry:
                    continue
                meta, path = entry.split(b"\t", 1)
                mode, kind, oid = meta.decode().split()
                path = path.decode()
                if (
                    mode not in {"100644", "100755"}
                    or kind != "blob"
                    or path.startswith("/")
                    or ".." in Path(path).parts
                ):
                    raise ValueError("unsupported planning tree")
                data = planning_output(
                    "git_blob",
                    ["/usr/bin/git", "-C", str(repo), "cat-file", "blob", oid],
                    timeout=20,
                )
                total += len(data)
                if total > 2097152:
                    raise ValueError("planning tree too large")
                target = snapshot / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            evidence = cto._repo_evidence(snapshot, name)
        plan = cto._central_cto(spec, repo, evidence, hashlib.sha256(raw).hexdigest())
        plan["baseline_revision"] = remote_main
        scope = [
            p
            for p in policy["allowed_scope"]
            if p in plan["scope"] and p in evidence["files"]
        ]
        if (
            not scope
            or select_specialists(spec, plan) != policy["specialists"]
            or plan["clarification_required"]
        ):
            raise ValueError("scope or specialist requires clarification")
        path = (
            Path(policy["gateway_state"])
            / "cto-plans"
            / f"{job['project']}-{job['task_id']}.json"
        )
        if (
            path.exists()
            and json.loads(path.read_bytes())["delivery"]["state"] != "pending"
        ):
            raise ValueError("never rewrite an already attempted historical plan")
        cto._validate_plan(plan)
        cto._atomic(path, plan)
        return {
            "repository": str(repo),
            "scope": scope,
            "baseline_revision": remote_main,
            "plan_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "spec_path": str(repo / ".dev/tasks" / name),
        }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage",
        choices=(
            "plan",
            "developer",
            "qa",
            "reviewer",
            "prepare",
            "publish",
            "completion",
        ),
    )
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        policy, _ = protected_json(args.policy)
    except (OSError, ValueError) as exc:
        raise WorkerFailure(failure(args.stage, "policy_read", exc)) from None
    # Role identities cannot traverse alfred's home, so the Evidence sandbox mounts
    # the same gateway directory read-only here. Without the mount, the original
    # path is used and an unobservable PAUSE/STOP still fails closed.
    gateway = (
        GATEWAY_VIEW if GATEWAY_VIEW.is_dir() else Path(policy["gateway_state"])
    )
    if (
        policy.get("schema") != "alfred.fresh-v1-policy/1"
        or policy.get("enabled") is not True
        or any((gateway / name).exists() for name in ("PAUSE", "STOP"))
    ):
        raise ValueError("fresh V1 dispatch is disabled or paused")
    try:
        job, _ = protected_json(args.job / "job.json")
    except (OSError, ValueError) as exc:
        raise WorkerFailure(failure(args.stage, "job_read", exc)) from None
    identity(job["project"], job["task_id"])
    if (
        args.job != Path(policy["jobs"]) / job["project"] / job["task_id"]
        or job["project"] != policy["project"]
    ):
        raise ValueError("job outside activated policy")
    if args.stage == "plan":
        output = prepare_plan(job, policy)
    elif args.stage == "developer":
        import io
        from contextlib import redirect_stdout

        from developer_v1 import run_task

        request, _ = protected_json(args.job / "execution.json")
        request_path = (
            Path(policy["developer_state"])
            / f"request-{job['project']}-{job['task_id']}.json"
        )
        write_once(request_path, request)
        with redirect_stdout(io.StringIO()):
            run_task.main(
                [
                    "--request",
                    str(request_path),
                    "--models",
                    policy["models"],
                    "--gateway-root",
                    policy["gateway_root"],
                    "--gateway-state",
                    policy["gateway_state"],
                    "--registry",
                    policy["registry"],
                    "--grant-root",
                    policy["grant_root"],
                    "--state-root",
                    policy["developer_state"],
                ]
            )
        output = {"state": "ready_for_independent_qa"}
    elif args.stage == "qa":
        from independent_qa.worker import run

        base = args.job / "qa-input"
        output = run(
            base / job["project"] / job["task_id"] / "qa-input.json",
            args.job / "qa-output",
            base / "registry.json",
            base / "gateway",
            base / "grants",
            base / "config.json",
        )
    elif args.stage == "reviewer":
        from independent_reviewer.worker import run

        base = args.job / "reviewer-input"
        output = run(
            base / "reviewer-handoff.json",
            base / "qa-report.json",
            base / "snapshot",
            base / "cto-plan.json",
            base / "grant.json",
            base / "spec.md",
            base / "config.json",
            args.job / "reviewer-output",
        )
    elif args.stage in {"prepare", "publish"}:
        from draft_pr_publisher.worker import prepare, publish

        base = args.job / "publisher-input"
        paths = {
            "config_path": base / "config.json",
            "registry_path": base / "registry.json",
            "handoff_path": base / "publication-handoff.json",
            "review_path": base / "review-report.json",
            "qa_path": base / "qa-report.json",
            "qa_handoff_path": base / "reviewer-handoff.json",
            "plan_path": base / "cto-plan.json",
            "grant_path": base / "grant.json",
            "spec_path": base / "spec.md",
            "source_repo": base / "source.git",
        }
        if args.stage == "prepare":
            plan, digest = prepare(output_root=args.job / "publisher-output", **paths)
            output = {"publication_plan_sha256": digest, "status": plan["status"]}
        else:
            output = publish(
                output_root=args.job / "publisher-output",
                authorization_path=args.job / "publication" / "authorization.json",
                token_file=Path(policy["publisher_token"]),
                **paths,
            )
    else:
        from completion_integration.runtime import run

        output = run(args.job / "completion" / "config.json", send=True)
    print(json.dumps(output, sort_keys=True))


def worker_main(argv=None):
    """Process boundary: redact exceptions before any traceback can escape."""
    try:
        main(argv)
    except Exception as exc:  # noqa: BLE001 - never emit credentials/model output
        stage = (argv or sys.argv[1:] or [None])[0]
        from fresh_v1.diagnostics import STAGES

        if stage not in STAGES:
            raise SystemExit(1) from None
        evidence = (
            exc.evidence
            if isinstance(exc, WorkerFailure)
            else failure(stage, "python", exc)
        )
        print(json.dumps(evidence, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    worker_main()
