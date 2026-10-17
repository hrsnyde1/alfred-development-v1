# handoff.5 host procedure

## Why
- **T-0006 (Gate 6):** the Developer completed, and the QA worker started, but it
  failed with `python/permission_denied`.
- **The cause:** `fresh_v1/role.py` checks `PAUSE` and `STOP` in
  `/home/alfred/Alfred/gateway` before every stage. On Python 3.12,
  `Path.exists()` raises EACCES when the directory cannot be searched.
- **Who is affected:** the role identities `alfredqa`, `alfredreview` and
  `alfredpublish`. None of them can traverse `/home/alfred` (mode 750). Only
  `alfredqa` already had `--x` on it.
- **Why not widen access:** giving the Reviewer and Publisher traversal of
  alfred's home would expose its world-readable files, such as
  `~/alfred-data.tar.gz`, to the identity that holds the GitHub token.

## What changes (two files)

| Destination | Change |
| --- | --- |
| `/etc/systemd/system/alfred-development-evidence.service.d/40-fresh-v1.conf` | Adds `BindReadOnlyPaths=/home/alfred/Alfred/gateway:/run/alfred-fresh-v1-gateway`, a read-only view of the same directory inside the sandbox. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py` | Checks `PAUSE` and `STOP` in that view when it exists, and otherwise in the original path. An unobservable state still raises, so the check fails closed. |

**Prerequisite:** the gateway directory grants the three role identities search
(`--x`) only, through an access entry. This was applied on 2026-10-17. Role
identities can test whether `PAUSE` or `STOP` exists, but cannot list the
directory or read its 0600 files.

The installer refuses unless all of these hold:
- PAUSE is present;
- both destinations have exactly their handoff.4 bytes;
- the seven other runtime files match their pins;
- the activation marker is unchanged.

It writes a root-only backup and rolls itself back on any fault. It performs no
service action.

## Verification
`verification/role_sandbox_preflight.py` runs a read-only probe for each role
identity inside a transient unit that carries the installed Evidence unit's
sandbox settings, using `runuser` as the host does. The probe covers:
- the gateway view;
- the libraries and the job root;
- the repository and the writable state;
- `codex login status`;
- QA's bwrap test sandbox;
- the publisher's token contract;
- DNS and HTTPS reachability of github.com.

Before handoff.5 was built, the preview (`--with-gateway-view`) returned
`PASS` for all four roles: 64 checks and 0 failures.

## After install
- **Held tasks:** T-0003 through T-0006 stay held and untouched. The poll skips
  them.
- **Next run:** Gate 6 is retried with a fresh request, T-0007.

## Rollback
Run in a root shell with PAUSE present:

```
install_patch.py rollback --backup <backup>
```

Then run `systemctl daemon-reload`.
