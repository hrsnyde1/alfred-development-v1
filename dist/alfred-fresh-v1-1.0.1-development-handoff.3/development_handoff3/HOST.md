# handoff.3 host procedure

## Why
T-0004 (Gate 6) held at the Developer stage with `python/read_only_filesystem`. The
Developer's first write claims its grant, `execution-<ref>.json`, in
`/var/lib/alfred-development-grants`. The Evidence service runs every stage
under `ProtectSystem=strict`, and the fresh V1 drop-in did not list that
directory in `ReadWritePaths`. Nothing executed: there was no claim, no model
call and no worktree edit. The approval had already expired (`MAX_AGE` 300 s),
and a held stage is never retried.

The host poll advances only the first unfinished task each tick. It skipped
only an uncertain development-challenge send (T-0003), so T-0004 would also
have blocked every later request.

## What changes (two files)

| Destination | Change |
| --- | --- |
| `/etc/systemd/system/alfred-development-evidence.service.d/40-fresh-v1.conf` | Adds `ReadWritePaths=/var/lib/alfred-development-grants`. Every other line is unchanged. |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/host.py` | A task with a recorded `<stage>.failure.json` is skipped and reported as held, like T-0003. An attempt with no failure evidence still blocks. Nothing is modified or retried. |

The installer refuses unless all of these hold:
- PAUSE is present;
- both destinations still have exactly their handoff.2 bytes;
- the six unchanged `fresh_v1` runtime files still match their pins;
- the Developer activation marker is unchanged.

It writes a root-only backup and rolls itself back on any fault. It performs no
service action.

## Operator steps (root shell; pins are in RELEASE.md)

1. Confirm PAUSE and idle workers, exactly as in the handoff.2 HOST.md
   `assert_idle`.
2. Copy the archive to `/root`, check the archive pin, and extract it into a
   new 0700 review directory with `--no-same-owner --no-same-permissions`.
3. Check the installer pin. Then run `install_patch.py verify` with the
   manifest pin.
4. Run `install_patch.py install` with a new backup directory. It should print
   `INSTALLED_HELD`.
5. Run `systemctl daemon-reload`. Do not restart anything. The Evidence timer
   uses the new unit and code on its next run.
6. Check `sha256sum -c installed-after.sha256`, and that
   `systemctl show alfred-development-evidence.service -p ReadWritePaths`
   lists the grant store.

## After install
- **T-0004:** stays held for good, untouched, like T-0003. Never delete its files.
- **Next run:** remove PAUSE only for one fresh Gate 6 request. It becomes
  T-0005 and goes through the normal approval chain.

## Rollback
Run in a root shell with PAUSE present:

```
install_patch.py rollback --backup <backup>
```

Then run `systemctl daemon-reload`.
