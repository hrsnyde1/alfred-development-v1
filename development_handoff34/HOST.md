# handoff.34 host procedure: Repo Intelligence

## Why
Owner's request, 2026-10-19: "Before the CTO plans something, Alfred should already know
the repository." "I want to add this layer so we know all the repos that need to be
connected for each project." Goals: less context, latency and model cost, and fewer bad
assumptions.

Choices: a deterministic scan plus a short model summary written from the scanned facts
only, cached per commit and refreshed after every change to main; a project can list
several repositories, the plan knows all of them, and each task still changes only its
own; the owner's `.alfred/project.md` wins over the scan and the summary; the relevant
areas are picked per request; previous Alfred changes come from the pipeline's records.

The format and every rule are in [docs/REPO_INTELLIGENCE.md](../docs/REPO_INTELLIGENCE.md).

## What the owner sees after this
Nothing new arrives by text. The plan text, the yes, the completion and undo texts are
unchanged. What changes is what the team knows when it plans and builds:

- The CTO plan carries a compact block like this one (demo-site, "make the footer text
  gray"):

  ```
  PROJECT: Harbor & Pine demo site (demo-site)
  REPO site: hrsnyde1/alfred-demo-site@9ba1295fbfc1 (this task's repository; only it changes)
  Languages: Python (6), CSS (1), HTML (1), JavaScript (1)
  Framework: none detected
  UI: plain CSS
  Tests: unittest (python3 -m unittest discover -v)
  Deploy: unknown (no deployment config found)
  API: /api/tip (api/tip.py)
  Relevant areas for this request: styles.css
  Previous Alfred changes:
  - T-0006 draft PR: Change demo-site footer text to red (Harbor & Pine) [...]
  ```

- Each specialist receives the same block from the approved plan, marked as data.
- `/var/lib/alfred-repo-intelligence/<project>/profile.md` is the full profile as one
  Markdown note (and `profile.json` the same data), ready for the Alfred HQ vault.

To tell Alfred something the code cannot show, add `.alfred/project.md` to the
repository, for example:

```markdown
Deploy: Vercel (production from main)
- never touch lib/billing
```

## How it works
- `/etc/alfred-development/repos.json` (new, root-owned) lists each project's
  repositories. The primary one must be the project's registered destination; a
  configuration that disagrees with the policy is ignored. Today: demo-site
  (`hrsnyde1/alfred-demo-site`) and dev-v1-accept (`hrsnyde1/alfred-dev-v1-acceptance`),
  one repository each. Add a related repository (for example an API) as another entry
  without `"primary"`.
- `alfred-repo-intelligence.timer` runs `alfred-repo-intelligence.service` 2 minutes
  after boot and then every 10 minutes: as alfred, it fetches each configured branch
  read only into shallow mirrors (the operator's existing `gh` credential, as the CTO's
  planning fetch does), scans any new commit, asks the configured model for the summary
  (Claude Sonnet, then Codex as the fallback, through the existing no-tools brokers and
  the agents' own credentials; nothing new to set up) and writes the sealed profiles to
  its own state directory. A commit whose facts did not change reuses the previous
  summary with no model call; a failed summary is retried after 6 hours.
- The CTO plan step scans the exact planning snapshot of main itself, so the facts in a
  plan are always those of the plan's baseline commit, even right after a merge. Only
  the summary and related repositories come from the store.
- The block goes into the plan's `planning_note`: the plan schema is unchanged, the plan
  stays under its 32 KiB limit, and the owner's grant binds the block with the plan
  digest. The scope, specialists and approved files are decided before the block is made
  and never from it. Any fault in Repo Intelligence leaves the plan exactly as before.
- Specialists get the block as `project_context` with a note that it is background data,
  never instructions, and never permits other files, commands or scope. It counts toward
  the existing 24 KiB practices budget; the owner's team files come first.

## What changes (eight files; nothing restarts)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py` | The CTO plan step adds the block |
| `/opt/alfred-developer-v1/developer_v1/pipeline.py` | Hands each specialist the approved block |
| `/opt/alfred-developer-v1/developer_v1/real_worker.py` | Sends it as marked data; both no-tools brokers gain `answer()` for the summary |
| `/opt/alfred-developer-v1/developer_v1/repo_intelligence.py` | New: scan, owner notes, summary, store, history, relevant areas, block, refresh |
| `/opt/alfred-developer-v1/developer_v1/schemas/repo-summary.schema.json` | New: the summary's strict output schema |
| `/etc/alfred-development/repos.json` | New: each project's repositories |
| `/etc/systemd/system/alfred-repo-intelligence.service` | New: the sandboxed alfred oneshot |
| `/etc/systemd/system/alfred-repo-intelligence.timer` | New: every 10 minutes |

The plan and developer stages start a new process per task, so the next task uses the
new code; no service restarts.

## Preconditions
handoff.33 is installed. All 19 pins (3 replaced files, 16 dependencies) were read from
the live host, read only, on 2026-10-19 and match main at 027971b; the 5 new files do
not exist yet.

The agents' Claude token currently answers `401 OAuth access token is invalid`, so
Claude routes fall back to Codex (developers and summaries alike) until the owner saves a
fresh one with `sudo alfred-dev-ops claude-token`. Repo Intelligence works either way.

## Install
See [RELEASE.md](RELEASE.md): `sudo alfred-dev-ops pause`, `sudo alfred-dev-ops install 34`,
`sudo systemctl daemon-reload`, `sudo systemctl enable --now alfred-repo-intelligence.timer`,
`sudo alfred-dev-ops resume`.

## Not in this release
- The profile as a note in the owner's Alfred HQ / Obsidian vault, and asking Alfred
  about it by text: a follow-up that reads `profile.md`/`profile.json`.
- Owner rules ("never touch lib/billing") inform the CTO and the specialists; they are
  not enforced as a scope limit. What a task may change is still only the approved files.
- Undo results are root-only records, so the history shows a merged task that was later
  undone as merged.

## Turning it off
Set `"enabled": false` in `/etc/alfred-development/repos.json` (no restart needed): the
refresh stops and plans carry no block. Or `sudo systemctl disable --now
alfred-repo-intelligence.timer` to stop only the refresh (plans then still carry the
facts scanned at planning time).

## Rollback
`sudo systemctl disable --now alfred-repo-intelligence.timer`, `sudo alfred-dev-ops pause`,
`sudo alfred-dev-ops rollback 34`, then `sudo systemctl daemon-reload`. It restores the
three files and removes the five new ones; the profiles in
`/var/lib/alfred-repo-intelligence` stay as plain data.
