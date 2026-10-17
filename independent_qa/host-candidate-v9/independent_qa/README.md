# Alfred Development V1: Independent QA

`worker.py` consumes the Developer's immutable `qa-input.json`, the matching
Developer report, the canonical Gateway registry and CTO plan, the filed task,
the completed owner grant evidence, and Git objects. It writes only under its
separate QA output root. The Developer repository and grant store are read only.

The worker verifies the project and task, plan and scope, grant execution chain,
Git baseline, Developer commit list, final worktree revision and tree, actual
changed paths, and SHA-256 hashes. Developer-reported tests are checked for
handoff structure but never counted as QA test results. A source snapshot is
built from the verified Git tree and mounted read only in Bubblewrap with no
network namespace. Tests have a 45-second deadline, CPU and memory limits, and
a 16 KiB output cap. Test commands come only from the `CHECKS` catalog in
`worker.py`; `config.json` selects check IDs and maps canonical acceptance
criteria to those checks. The catalog currently supports Python unittest,
pytest, fixed calculator examples, and Node's native test runner. Additional
languages require reviewed catalog entries and a project mapping. There is no
shell command field in the handoff or config.

The optional Codex analysis uses the authenticated local CLI with a distinct
`codex/gpt-6.1-sol` model identity, a read-only empty workspace, and tools
disabled. Its actual use is recorded in `qa_model`; unavailable analysis is
recorded as an informational finding. Deterministic verification and tests
decide PASS or FAIL regardless of model availability.

Output contracts:

- `schemas/qa-report.schema.json`: durable PASS, FAIL, or BLOCKED report with
  source, test, acceptance, finding, and evidence fields.
- `schemas/reviewer-handoff.schema.json`: PASS-only handoff pinned to the exact
  final revision, changed file hashes, and report SHA-256.
- `schemas/correction-request.schema.json`: FAIL-only request tied to the task,
  responsible assignment, failed revision, and report SHA-256. It cannot
  authorize another edit; a new owner approval is required before correction.

`qa-report.json` is created once under an output-root/project/task path and
protected by a per-task file lock. An identical replay returns that report and
recovers a missing handoff. An input change cannot overwrite it. A correction
cycle therefore uses a new, separately authorized QA attempt directory; the
failed report, Developer commit, and evidence remain available.

## Staged verification

From the Development Lab root, run:

```sh
python3 -m unittest tests.test_independent_qa -v
python3 -m independent_qa.worker \
  --qa-input /var/lib/alfred-development-state/dev-v1-accept/T-0002/qa-input.json \
  --output-root independent_qa/staging-final \
  --registry /home/alfred/Git/alfred/registry/projects.yaml \
  --gateway-state /home/alfred/Alfred/gateway \
  --grant-root /var/lib/alfred-development-grants
```

The suite creates and discards writable Git fixtures. The T-0002 run reads
host evidence and writes only its staged QA report and Reviewer handoff.
Bubblewrap needs a host execution context that permits user namespaces.

## Minimal host installation and controlled acceptance

No service or restart is needed. After reviewing this staged candidate, install
this package and config in a dedicated read-only location such as
`/opt/alfred-independent-qa-v1`. The host installer copies the exact required
Gateway, grant, and Developer evidence into a root-owned, read-only QA handoff;
the independent QA identity cannot enter the original protected state trees.
The administrator preflight and host acceptance verifier compare every copy to
its canonical source. Give that identity write
access only to a separate QA state root, such as
`/var/lib/alfred-independent-qa-state`. Keep the Developer worktrees, source
repository, Gateway registry, grant store, and Developer state inaccessible
for that identity except the reviewed Git worktrees and QA handoff. Confirm
Python 3, PyYAML, Git, Bubblewrap, and the authenticated
Codex CLI are available. The deterministic worker still runs when Codex is
unavailable.

For controlled T-0002 host acceptance, use the exact installed handoff paths in
`HOST_OPERATOR.md`, then validate
`qa-report.json` and `reviewer-handoff.json` against their schemas. Check that
the report is PASS, `calculator_examples` and `python_unittest` both exited 0,
the only changed path is `calculator.py`, Developer commit is
`867fde90acf3f0055af79bda53a0fccb55f6bf34`, final revision is
`89ba188f8a2f801d433a30c9c21363efb3e1043d`, and the handoff report hash
matches the report bytes. Verify Developer source and worktree Git status did
not change. Deliver the handoff to Independent Reviewer. Reviewer approval and
Draft PR publication are later stages.

## Rollback

Stop invoking the QA command and follow `HOST_OPERATOR.md` to restore the
saved ACLs and preserve the installed package, QA output, and evidence handoff
under the protected backup path. Developer artifacts, commits, Gateway files,
grants, and existing services require no rollback because QA does not modify
their contents.
