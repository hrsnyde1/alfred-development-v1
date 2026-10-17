# handoff.3 release pins and root commands

Staging review artifact. Built by `development_handoff3/build_release.py`.
`--reproduce` rebuilds it byte for byte. The procedure is in
[HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.3.tar.gz` | `e95b037ff227f33a1894e1e7c1e89bee1cb5f14e691938f3ade399bcab65a79b` |
| Release `MANIFEST.sha256` (10 payload files) | `50502fa51b9977505b343c496943464a78c4ad2c3e9e8d7317743444a970c0ca` |
| Release `development_handoff3/install_patch.py` | `c3b736be32a3c8d5f96c51d4288021ddd5557d0d39060c3cbc89eb718ed5234f` |
| Installed `host.py` after | `11ad94611967226be2fdee31158c3a78bd6b7b22cb9a6d7ab4a8dbdde75c2645` |
| Installed `40-fresh-v1.conf` after | `71a5c7ee1326ed625d98d5b36945cccb4e44b7603b3c2e0a004b6d028040b462` |

Staging evidence:
- **Release tests:** `staging-tests.xml` records 57 passed and 0 failed across
  the sandbox-paths, recorded-failure-skip and installer tests.
- **Mutation check:** the skip tests fail when the old `host.py` is restored.
- **Dry run:** the real archive was extracted with `--no-same-owner
  --no-same-permissions`, and `verify` reported 10 files.
- **Live preconditions:** checked read-only as alfred. Both destinations hold
  their handoff.2 bytes, and the six runtime dependencies match.

## Root commands

Run these in a root shell (`sudo -i`; the prompt ends in `#`). PAUSE must be
present. Stop at the first line that does not match.

**1. Copy, pin-check, extract and verify:**

```bash
cp /home/alfred/alfred-development-v1/dist/alfred-fresh-v1-1.0.1-development-handoff.3.tar.gz /root/ && echo 'e95b037ff227f33a1894e1e7c1e89bee1cb5f14e691938f3ade399bcab65a79b  /root/alfred-fresh-v1-1.0.1-development-handoff.3.tar.gz' | sha256sum -c - && install -d -m 0700 /root/alfred-fresh-v1-development-handoff-3-review && tar --no-same-owner --no-same-permissions -xzf /root/alfred-fresh-v1-1.0.1-development-handoff.3.tar.gz -C /root/alfred-fresh-v1-development-handoff-3-review && R=/root/alfred-fresh-v1-development-handoff-3-review/alfred-fresh-v1-1.0.1-development-handoff.3 && echo "c3b736be32a3c8d5f96c51d4288021ddd5557d0d39060c3cbc89eb718ed5234f  $R/development_handoff3/install_patch.py" | sha256sum -c - && /usr/bin/python3 -I -B $R/development_handoff3/install_patch.py verify --release $R --manifest 50502fa51b9977505b343c496943464a78c4ad2c3e9e8d7317743444a970c0ca && test -f /home/alfred/Alfred/gateway/PAUSE && echo PAUSE_OK && test ! -e /root/alfred-fresh-v1-development-handoff-3-backup && echo BACKUP_ABSENT
```

Expect two `OK` lines, `{"files": 10}`, `PAUSE_OK` and `BACKUP_ABSENT`.

**2. Confirm no workers are running.** Every line should read `inactive 0`. If
the Gateway shows `activating`, wait 30 seconds and check again.

```bash
for u in alfred-development-evidence alfred-development-gateway alfred-dev-qa-runner alfred-dev-qa-snapshot alfred-dev-qa-auth; do echo "$u $(systemctl show $u.service -p ActiveState --value) $(systemctl show $u.service -p MainPID --value)"; done
```

**3. Install, reload unit definitions (no restart) and verify:**

```bash
R=/root/alfred-fresh-v1-development-handoff-3-review/alfred-fresh-v1-1.0.1-development-handoff.3; /usr/bin/python3 -I -B $R/development_handoff3/install_patch.py install --release $R --manifest 50502fa51b9977505b343c496943464a78c4ad2c3e9e8d7317743444a970c0ca --backup /root/alfred-fresh-v1-development-handoff-3-backup 2>&1 | tee /root/handoff-3.log; echo "HANDOFF3_EXIT=${PIPESTATUS[0]}" | tee -a /root/handoff-3.log; systemctl daemon-reload && sha256sum -c $R/development_handoff3/installed-after.sha256 && systemctl show alfred-development-evidence.service -p ReadWritePaths | tr ' ' '\n' | grep -x '/var/lib/alfred-development-grants' && test -f /home/alfred/Alfred/gateway/PAUSE && echo PAUSE_STILL_SET
```

Expect all of these:
- `"status": "INSTALLED_HELD"` and `HANDOFF3_EXIT=0`;
- two `OK` lines;
- `/var/lib/alfred-development-grants`;
- `PAUSE_STILL_SET`.

Do not restart any service. The Evidence timer picks up the new unit and code
on its next run.
