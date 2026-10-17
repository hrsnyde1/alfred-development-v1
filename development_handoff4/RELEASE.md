# handoff.4 release pins and root commands

Staging review artifact. Built by `development_handoff4/build_release.py`.
`--reproduce` rebuilds it byte for byte. The why and how are in
[HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.4.tar.gz` | `0093de25ea8fbe798d8cec80981cb92cb6a5d0db3f8eeb56ce932ee7071d0039` |
| Release `MANIFEST.sha256` (12 payload files) | `7d4d323fbecf625d505cbd76890bade67b6bc19dff5010992869a020208569c1` |
| Release `development_handoff4/install_patch.py` | `e1801cb3b0a725d8968f7876f5da884392c6e6b5b39f59daec56674bd28424ac` |

Staging evidence:
- **Release tests:** `staging-tests.xml` records 29 passed and 0 failed across
  the QA recovery, installer and sandbox-path tests. Gate 1 passes all eight
  suites.
- **Mutation check:** removing the recovery branch fails 2 tests; removing the
  failure recording fails or errors 8.
- **Dry run:** the real archive was extracted, and `verify` reported 12 files.
- **Live preconditions:** checked read-only as alfred. The three destinations
  hold their handoff.3 bytes, `qa_recovery.py` is absent, and the five runtime
  dependencies match.

## Root commands

Run these in a root shell (`sudo -i`; the prompt ends in `#`). PAUSE must be
present. Stop at the first line that does not match, and paste the output.

**1. Copy, pin-check, extract and verify:**

```bash
cp /home/alfred/alfred-development-v1/dist/alfred-fresh-v1-1.0.1-development-handoff.4.tar.gz /root/ && echo '0093de25ea8fbe798d8cec80981cb92cb6a5d0db3f8eeb56ce932ee7071d0039  /root/alfred-fresh-v1-1.0.1-development-handoff.4.tar.gz' | sha256sum -c - && install -d -m 0700 /root/alfred-fresh-v1-development-handoff-4-review && tar --no-same-owner --no-same-permissions -xzf /root/alfred-fresh-v1-1.0.1-development-handoff.4.tar.gz -C /root/alfred-fresh-v1-development-handoff-4-review && R=/root/alfred-fresh-v1-development-handoff-4-review/alfred-fresh-v1-1.0.1-development-handoff.4 && echo "e1801cb3b0a725d8968f7876f5da884392c6e6b5b39f59daec56674bd28424ac  $R/development_handoff4/install_patch.py" | sha256sum -c - && /usr/bin/python3 -I -B $R/development_handoff4/install_patch.py verify --release $R --manifest 7d4d323fbecf625d505cbd76890bade67b6bc19dff5010992869a020208569c1 && test -f /home/alfred/Alfred/gateway/PAUSE && echo PAUSE_OK && test ! -e /root/alfred-fresh-v1-development-handoff-4-backup && echo BACKUP_ABSENT
```

Expect two `OK` lines, `{"files": 12}`, `PAUSE_OK` and `BACKUP_ABSENT`.

**2. Confirm no workers are running.** Every line should read `inactive 0`.

```bash
for u in alfred-development-evidence alfred-development-gateway alfred-dev-qa-runner alfred-dev-qa-snapshot alfred-dev-qa-auth; do echo "$u $(systemctl show $u.service -p ActiveState --value) $(systemctl show $u.service -p MainPID --value)"; done
```

**3. Install, reload unit definitions (no restart) and verify:**

```bash
R=/root/alfred-fresh-v1-development-handoff-4-review/alfred-fresh-v1-1.0.1-development-handoff.4; /usr/bin/python3 -I -B $R/development_handoff4/install_patch.py install --release $R --manifest 7d4d323fbecf625d505cbd76890bade67b6bc19dff5010992869a020208569c1 --backup /root/alfred-fresh-v1-development-handoff-4-backup 2>&1 | tee /root/handoff-4.log; echo "HANDOFF4_EXIT=${PIPESTATUS[0]}" | tee -a /root/handoff-4.log; systemctl daemon-reload && sha256sum -c $R/development_handoff4/installed-after.sha256 && systemctl show alfred-development-evidence.service -p ReadWritePaths | tr ' ' '\n' | grep -x '/home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo' && test -f /home/alfred/Alfred/gateway/PAUSE && echo PAUSE_STILL_SET
```

Expect all of these:
- `INSTALLED_HELD` and `HANDOFF4_EXIT=0`;
- four `OK` lines;
- the repository path;
- `PAUSE_STILL_SET`.

**4. Inspect T-0005 (read-only).** The last line is the inspection digest.

```bash
/usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0,"/usr/local/lib/alfred-fresh-v1"); from fresh_v1.qa_recovery import main; main()' inspect
```

**5. Authorize the one QA recovery, then verify it.** Paste the digest from
step 4 in place of `<DIGEST>`. The decision expires after one hour if unused,
so remove PAUSE (step 6) within that hour.

```bash
/usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0,"/usr/local/lib/alfred-fresh-v1"); from fresh_v1.qa_recovery import main; main()' authorize --inspection-sha256 <DIGEST> --operator-reference gate6-T-0005-qa-recovery && /usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0,"/usr/local/lib/alfred-fresh-v1"); from fresh_v1.qa_recovery import main; main()' verify
```

Expect `ONE_QA_RECOVERY_AUTHORIZED_HELD`, then
`QA_RECOVERY_EVIDENCE_VERIFIED_NO_EXECUTION`.

**6. Resume:**

```bash
rm -f /home/alfred/Alfred/gateway/PAUSE
```

On the next tick, QA runs once as `qa-recovery-1`, then the Reviewer runs. The
publication approval then arrives on your phone. Reply in thread with its exact
phrase, and the draft PR follows. No new development approval is needed.
