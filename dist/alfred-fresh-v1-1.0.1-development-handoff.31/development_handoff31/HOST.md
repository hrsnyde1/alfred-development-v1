# handoff.31 host procedure: the pipeline merges its own approved work, and "undo" takes it back

## Why
Owner's instruction, 2026-10-18: "I want … the CTO to be able to merge the repositories
on each GitHub. I don't want to have to be the one to do it. It should automatically do
it and update the code." Choices: auto-merge yes; undo by replying "undo"; squash merges.

## What the owner sees after this

1. **The request preview** (unchanged). Reply "yes" to start.
2. **All done** (one text, after QA and the Reviewer pass):
   "All done with demo-site. It's built, tested, reviewed and merged into main." plus the
   commit link, and "Reply undo within 24 hours to take it back."
3. Only if you reply **undo** to that text: "Undone. demo-site is back to how it was
   before that change." plus the link to the undo commit.

If the pipeline can't merge on its own, nothing is merged and the last text says so,
with the draft PR link: "Built, tested and reviewed, but I couldn't merge it on my own:
…. It's ready for you to merge." That happens when main changed after QA and the
Reviewer checked the change, or when GitHub refuses the merge (see "GitHub" below).

If an undo would clash with something merged to main since, nothing is changed and you
get "I couldn't undo that change … on my own: main has changed since, and taking it back
would clash with the newer work. Nothing was changed."

## How it works (all recorded, nothing repeated)
- After the Publisher opens the draft PR, the host asks the intake for your merge policy
  once (`merge-decision`). For a project listed in `/etc/alfred-development/delegation.json`
  with `"merge_approval": "delegated"`, the intake records the decision
  (`merge-delegation-*.json` in the grant store, naming the policy in force; it never
  claims a reply from you) and root seals a merge authorization bound to the exact
  publication plan, draft PR and approved commit.
- The Publisher (its own identity and token, `alfredpublish`) runs the recorded `merge`
  stage once: main must still be the commit that was tested; it marks the draft PR ready
  and squash-merges it, pinned to the approved commit, then reads GitHub back (one
  squash commit, on the tested main, with exactly the approved files).
- The completion text is built from that record and GitHub's readback.
- The intake opens a 24-hour undo window bound to that exact text (its Photon receipt).
  Your native reply "undo" (also "undo it", "revert", "take it back"), from your number,
  in the same DM, not forwarded, is recorded once as `undo-decision-*.json`. Any other
  reply to that text ("thanks!") is ordinary chat. A second "undo" does nothing.
- The Publisher then runs the recorded `revert` stage once: it reverts exactly that squash
  commit against main as it is now (`git merge-tree`), refuses if that clashes, refuses
  if the undo would touch any file the merged change did not, pushes the undo branch,
  opens an undo PR and squash-merges it. The intake sends you the one short result text.
- The squad chat says "🔀 … merged into main" and "↩️ … undone".

## What changes (fifteen files, one new; the intake restarts)

| Destination | Change |
| --- | --- |
| `/etc/alfred-development/delegation.json` | Adds `"merge_approval": "delegated"` (the project list is unchanged) |
| `/opt/alfred-developer-v1/developer_v1/owner_grants.py` | Accepts `merge_approval` `"owner"` or `"delegated"` (absent means `"owner"`) |
| `/opt/alfred-independent-qa-v1/independent_qa/worker.py` | QA's own copy of the same policy check (the handoff.30 lesson) |
| `/opt/alfred-developer-v1/developer_v1/publication_approval.py` | Records the delegated merge decision |
| `/opt/alfred-developer-v1/developer_v1/undo_approval.py` (new) | The verified "undo" reply |
| `/opt/alfred-developer-v1/developer_v1/trusted_intake_development.py` and `/usr/local/lib/alfred-v1.1/trusted_intake.py` | The merge and undo operations |
| `/opt/alfred-draft-pr-publisher-v1/worker.py` | Squash merge and exact revert |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/{handoffs,host,role,diagnostics}.py` | The recorded `merge-decision`, `merge`, `undo-window`, `undo` and `undo-notice` stages |
| `/usr/local/lib/alfred-completion-v1/completion_integration/{completion,runtime}.py` | "merged into main", the commit link, how to undo |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/squads.py` | The squad chat's merge and undo steps |

## Before installing: what the owner must do

1. **Install handoff.30 first.** This release pins QA's worker at handoff.30's bytes and
   refuses to install otherwise (nothing is changed).
2. **GitHub token: no change should be needed.** The Publisher already pushes branches
   (Contents: Read and write) and opens PRs (Pull requests: Read and write) with its own
   token, and those two permissions are exactly what marking a PR ready and
   squash-merging it need. If its token is a fine-grained token, confirm on
   github.com → Settings → Developer settings → Fine-grained tokens → the Publisher's
   token that both `hrsnyde1/alfred-demo-site` and `hrsnyde1/alfred-dev-v1-acceptance`
   are selected with **Contents: Read and write** and **Pull requests: Read and write**.
   If a merge is refused for permissions, you get the "couldn't merge it on my own" text
   and nothing is merged.
3. **Branch protection.** Both repositories allow squash merging (checked 2026-10-18).
   On each repository, open Settings → Branches (and Settings → Rules → Rulesets). If
   `main` requires approving reviews, status checks or merge queues, GitHub refuses the
   pipeline's merge and you get the "couldn't merge it on my own" text. To let it merge,
   remove that rule or add the Publisher token's account to the bypass list. Nothing else
   is needed when `main` is unprotected.

## Install

See [RELEASE.md](RELEASE.md): `sudo alfred-dev-ops pause`, `sudo alfred-dev-ops install 31`,
`sudo alfred-dev-ops resume`.

## Limits
- Undo works for 24 hours after the "merged" text, by replying to that text only. After
  that, or if that text's delivery was recorded as uncertain, revert it on GitHub.
- Merging updates the repository only. Alfred deploys nothing; anything that deploys from
  `main` (for example GitHub Pages) does what it already does on a merge.

## Turning it off
Set `"merge_approval": "owner"` (or remove the key) in
`/etc/alfred-development/delegation.json`. It applies to the next task that reaches the
merge step; you then merge each draft PR yourself, as before.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 31`. It restores every
file and removes `undo_approval.py`; recorded merges and undos stay as evidence.
