# Alfred Development V1 Draft PR Publisher

`worker.py prepare` checks the pinned Reviewer V4 publication handoff and report,
QA PASS report and handoff, CTO plan, development grant, task specification,
canonical project registry, and exact Git diff. It writes only an immutable
publication plan under its dedicated output root. It makes no network request.

`worker.py publish` repeats every check. Before any GitHub operation, it requires
a root-owned, non-user-writable authorization record that binds an authenticated
owner event to the exact publication plan digest. The existing development grant
does not authorize publication. A dedicated publisher identity alone can read
the repository-scoped token. No model or other Alfred stage receives it.

Publication compares the registered GitHub repository and default branch to the
remote, requires the remote base to equal the approved baseline, and uses a fresh
bare Git repository to push only the approved final commit to a deterministic
branch. It creates a Draft PR through GitHub's pull-request API. It never calls
merge, deployment, or ready-for-review endpoints. The output record pins the
branch, commit, QA and Reviewer digests, and Draft PR URL for Alfred's completion
notification. A retry reuses the completed result or checks GitHub for an
existing matching Draft PR before another create call.

`HOST_OPERATOR.md` contains the future administrator installation and rollback
procedure. This staging release performs no live GitHub write.
