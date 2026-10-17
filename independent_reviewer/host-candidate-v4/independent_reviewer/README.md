# Independent Reviewer V1

This on-demand worker accepts only the existing QA PASS handoff. It verifies
the pinned QA report bytes, handoff fields, plan and grant digests, task spec,
the final Git revision and tree, the actual diff, approved file scope and each
changed blob hash before invoking its separate `codex/gpt-6-astra` model.

The model receives only the diff, CTO objective and scope, acceptance criteria,
and QA test results. It has no tools, runs from an empty temporary directory,
and cannot read grant contents or QA files through the prompt. A model failure
produces BLOCKED. A concrete finding or failed criterion requests changes.

The worker never executes project code or invokes GitHub. It writes only its
review report and, when appropriate, a publication handoff or correction
request under the dedicated output root. An existing report is returned only
for the same input fingerprint; changed evidence is rejected.

Input arguments are `--handoff`, `--qa-report`, `--final-worktree`,
`--cto-plan`, `--grant`, `--task-spec`, `--config`, and `--output-root`.
The source path can be a dedicated, read-only Git clone of the final revision.
The QA report and authority records can be exact root-owned copies in a narrow
Reviewer evidence handoff; their SHA-256 values must match the pinned QA report.

`HOST_OPERATOR.md` documents staged release verification, future host
installation, permission checks, rollback, and controlled T-0002 acceptance.
