# handoff.12 host procedure: multi-project support

## Why
The pipeline was hard-wired to one project (the calculator): one policy, one
repository, two allowed files, specialists exactly `backend`. The owner asked to text
Alfred about the demo website ("add a light/dark mode to the demo site").

## What changes (eight files, one restart)

| Destination | Change |
| --- | --- |
| `/etc/alfred-fresh-v1/policy.json` | Schema 2: shared settings plus `projects` (`dev-v1-accept`, `demo-site`). Each task sees only its project's view; the calculator's view equals today's policy exactly, so in-flight work continues. Root-only, so pinned by content (`policy-before.json`), not bytes. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | Per-project views in the poll; one developer item per approved specialist (frontend and/or backend, no shared files); QA expects exactly those reports; checks whether another approval text is still open. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py` | Planning: the CTO's specialists must be within the project's allowed list; a request that names no files uses the project's allowed files; records the specialists. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/handoffs.py` | A task waiting on the owner no longer blocks later tasks; a task never sends an approval text while another is open (it waits its turn instead of risking an uncertain send). |
| intake (both paths) | "the demo site" names `demo-site`: multi-word IDs and registry aliases match when written naturally. One-word IDs (such as `alfred`) still need an exact match. |
| `/opt/alfred-independent-qa-v1/independent_qa/config.json` | Adds the `demo-site` QA profile (`python_unittest`). |
| `/etc/alfred-development/delegation.json` | Adds `demo-site` to owner-delegated development approval. |

## Owner steps outside the installer
1. **Registry entry** (protected; only the owner writes it): append
   `registry-demo-site.yaml` to `~/Git/alfred/registry/projects.yaml`.
2. **GitHub token for the Publisher**: the token in
   `/var/lib/alfred-draft-pr-private/github-token` must be able to push branches and
   open pull requests on `hrsnyde1/alfred-demo-site`. For a fine-grained token, add
   that repository with Contents and Pull requests read/write.
3. The lab clone `/home/alfred/alfred-development-lab/demo-site/repo` already exists
   (QA has read access, no git remote).

## Not in this release
- "Ship it" (merge, then update the local preview, then text "it's live"): handoff.13.
- Alfred's clarifying questions before filing (Hermes side).

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 12`. The policy file's
original bytes are restored from the backup.
