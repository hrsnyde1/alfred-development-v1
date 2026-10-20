# handoff.44 host procedure: Photon stalls you can clear, and the Development board feed

## Why
- **Silent stalls.** Three of the 2026-10-19/20 stalls left nothing in any log, so the
  handoff.43 watchdog may not see the next one. Hayden wants to clear a stall himself,
  from Alfred OS or by asking Alfred, and see the stalls in Alfred OS.
- **The Development board.** Alfred OS's board showed Hermes kanban, which the pipeline
  has not used since handoff.12. The real workflow of each task (plan, your yes,
  developers, QA, review, fix rounds, draft PR, merge, undo) lives in root-only records
  that no Alfred OS bridge can read.

## What changes

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/photon_watchdog.py` | Keeps a stall list and answers owner requests (below). The checks and limits from handoff.43 are unchanged. |
| `/etc/systemd/system/alfred-photon-watchdog.service` | State folder 0711 (was 0700) so the bridges can read `stalls.json`; may remove files in the request spool |
| `/etc/systemd/system/alfred-photon-requests.path` (new) | Starts the watchdog as soon as a request lands, instead of within 2 minutes |
| `/etc/sysusers.d/alfred-photon.conf` (new) | Group `alfredphoton`, members `alfredos` (Alfred OS) and `alfredmsg` (Hermes, so Alfred) |
| `/etc/tmpfiles.d/alfred-photon.conf` (new) | The spool `/var/lib/alfred-photon-requests`, `1770 root:alfredphoton` |
| `/usr/local/bin/alfred-photon-clear` (new) | What Alfred runs: `status`, `clear [--delay N]`, `delete <stall>` |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/dev_board.py` (new) | Every task's workflow, from the records |
| `/etc/systemd/system/alfred-dev-board.service` / `.timer` (new) | Sandboxed root oneshot every 20 seconds, no network; writes `/var/lib/alfred-dev-board/workflows.json` (0640 root:alfred) |

Requires handoff.43 installed: the watchdog and its unit must have exactly its bytes.

## The stall list
`/var/lib/alfred-photon-watchdog/stalls.json` (0644: times, legs and outcomes, nothing
secret). A stall opens the first time a run suspects one, and closes when:
- the watchdog restarts Photon (`cleared` by `watchdog`);
- inbound recovers by itself (`recovered`);
- you or Alfred clear it (`cleared` by `alfred-os` or `alfred`).

The last 50 closed stalls stay on the list; the journal keeps everything.

## Owner requests
A request is a small JSON file in the spool:
`{"schema": "alfred.photon-request/1", "action": "clear" | "delete", "by": "alfred-os" | "alfred", "stall": null | "s-…", "delay": 0-30}`.

- **clear** restarts Photon now, whether or not any check sees a stall: you are the
  detector for the silent ones. Every open stall closes as cleared by you; if none is
  open, one is recorded as "reported" and cleared.
- **delete** removes one stall from the list. If it is still open, Photon is restarted
  first.
- **Limits:** owner restarts are at most one per 5 minutes and 12 a day, separate from
  the watchdog's own limits. Two requests in one run share one restart.
- **delay** lets Alfred's reply go out before the restart stops Hermes.
- Each file is read once and removed, valid or not. A symlink, an odd name, a large file
  or bad JSON is refused. Who sent it comes from the file's owner (recorded as `user`),
  never from its text. The answer goes into `stalls.json` and the journal
  (`owner_request`).
- Only members of `alfredphoton` can write to the spool. The sticky bit stops them
  touching each other's files, and root decides everything.

## Asking Alfred
Alfred runs `alfred-photon-clear clear --delay 15` and tells you it is restarting. Hermes
restarts with Photon, so Alfred is gone for about a minute.

If iMessage itself is stalled, a text to Alfred won't arrive. Ask from Alfred OS's chat or
Telegram instead, or use the button in Alfred OS. Alfred needs to be in `alfredphoton`,
which applies from Hermes' next restart. The first clear restarts it anyway, so use
Alfred OS's button for that first one.

## The board feed
`dev_board.py` reads `/var/lib/alfred-v1-handoffs/<project>/T-*` and the developer
reports, like `squads.py` does.

What it writes per task: the goal's first line, the specialists and squads, the current
column, and each step's state, time and short detail (for example QA's top three
findings). It also writes the fix rounds, the developers' summaries, and the PR, merge
and undo links.

What it never writes: plans, approval phrases, challenges, grants, worktree paths or
credentials. A task whose records can't be read is skipped and counted, never guessed.

The development bridge serves it to Alfred OS as `GET /v1/development/workflows`
(hrsnyde1/alfred-hq).

## Rollback
Disable the new units, roll back with `alfred-dev-ops rollback 44` (restores handoff.43's
two files and removes the seven new ones), then `daemon-reload`. The group and the spool
may stay; they are inert without the path unit. See RELEASE.md.
