# handoff.6 release pins and root commands

Staging review artifact. Built by `development_handoff6/build_release.py`.
`--reproduce` rebuilds it byte for byte. The why and how are in
[HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.6.tar.gz` | `149f80e50846061c5501d4c2888fca512967e3a7bea23471258de15a284bb3c1` |
| Release `MANIFEST.sha256` (11 payload files) | `8605cb39b6bba9b0aafda37b18f41e8d1b44a0dba2d55e02f93fe900c433c129` |
| Release `development_handoff6/install_patch.py` | `d710e9190cbd1edbd9dda19b1ed1ad6a1ec6930919441144a78d000d99acecce` |
| Reviewer `host-candidate-v5` manifest | `62481e522cb78e1284d49a49f6a377773e80485a587c941a052427c0afd4efbe` |

Staging evidence:
- **Release tests:** `staging-tests.xml` records 30 passed and 0 failed.
- **Mutation check:** 4 of the 17 message tests fail with the old workers.
  These are exactly the progress-note cases.
- **Gate 1:** all ten suites pass. The handoff.2 tests now build from the pinned
  handoff.2 payload instead of the live source tree.
- **Reproduction:** a read-only rerun of T-0007's own model call showed the
  two-message reply (`status`, then the edits).
- **Dry run:** the real archive was extracted, and `verify` reported 11 files.
- **Live preconditions:** checked as alfred, including every file listed in both
  installed inventories. There were 0 mismatches.

## Root commands

Run these in a root shell (`sudo -i`; the prompt ends in `#`). PAUSE must be
present. Stop at the first line that does not match, and paste the output.

**1. Pause, copy, pin-check, extract and verify:**

```bash
touch /home/alfred/Alfred/gateway/PAUSE && cp /home/alfred/alfred-development-v1/dist/alfred-fresh-v1-1.0.1-development-handoff.6.tar.gz /root/ && echo '149f80e50846061c5501d4c2888fca512967e3a7bea23471258de15a284bb3c1  /root/alfred-fresh-v1-1.0.1-development-handoff.6.tar.gz' | sha256sum -c - && install -d -m 0700 /root/alfred-fresh-v1-development-handoff-6-review && tar --no-same-owner --no-same-permissions -xzf /root/alfred-fresh-v1-1.0.1-development-handoff.6.tar.gz -C /root/alfred-fresh-v1-development-handoff-6-review && R=/root/alfred-fresh-v1-development-handoff-6-review/alfred-fresh-v1-1.0.1-development-handoff.6 && echo "d710e9190cbd1edbd9dda19b1ed1ad6a1ec6930919441144a78d000d99acecce  $R/development_handoff6/install_patch.py" | sha256sum -c - && /usr/bin/python3 -I -B $R/development_handoff6/install_patch.py verify --release $R --manifest 8605cb39b6bba9b0aafda37b18f41e8d1b44a0dba2d55e02f93fe900c433c129 && test ! -e /root/alfred-fresh-v1-development-handoff-6-backup && echo BACKUP_ABSENT
```

Expect two `OK` lines, `{"files": 11}` and `BACKUP_ABSENT`.

**2. Install and verify.** The workers start anew for each stage, so there is no
reload and no restart:

```bash
R=/root/alfred-fresh-v1-development-handoff-6-review/alfred-fresh-v1-1.0.1-development-handoff.6; /usr/bin/python3 -I -B $R/development_handoff6/install_patch.py install --release $R --manifest 8605cb39b6bba9b0aafda37b18f41e8d1b44a0dba2d55e02f93fe900c433c129 --backup /root/alfred-fresh-v1-development-handoff-6-backup 2>&1 | tee /root/handoff-6.log; echo "HANDOFF6_EXIT=${PIPESTATUS[0]}" | tee -a /root/handoff-6.log; sha256sum -c $R/development_handoff6/installed-after.sha256 && test -f /home/alfred/Alfred/gateway/PAUSE && echo PAUSE_STILL_SET
```

Expect `INSTALLED_HELD`, `HANDOFF6_EXIT=0`, four `OK` lines and
`PAUSE_STILL_SET`.

**3. Gate 6, T-0008:** resume with

```bash
rm -f /home/alfred/Alfred/gateway/PAUSE
```

Then send a fresh request from your phone and reply in thread to each approval.
