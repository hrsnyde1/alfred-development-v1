# Same-server installer remediation v2 — staging validation

**Scope:** staging-only checks on 2026-10-14. No protected OS installation, account, service, firewall, credential or Photon action was performed. This file records synthetic and static evidence only.

| Command (from `photon-live-test/`) | Result |
|---|---|
| `./bin/node --test --test-isolation=none --test-reporter=tap tests/*.test.mjs` | 31 tests: **30 passed, 1 skipped, 0 failed**. The skip is the AF_UNIX bind test because this sandbox returns `EPERM`; it remains an OS acceptance requirement. Includes fixed control tokens, symlink/hardlink/oversized/unsafe result denial, network classification and the unchanged six-case native reply protocol. |
| `python3 -B -m unittest -v tests/test_payload_gate.py` | **11 passed, 0 failed**. Includes digest forgery, FIFO, oversized source, member count and entry caps, symlink/hardlink, source owner/mode, path swap, source mutation, interrupted handoff, archive member attacks and partial extraction. |
| `./bin/node scripts/verify-unit.mjs` | **PASS**: systemd 255 parser verification of test, probe, both control and results templates after staging-only executable rebasing. Real `RootDirectory` mount behavior remains untested. |

An initial `./scripts/dry-run.sh` attempt failed at `MANIFEST_MISMATCH` because it ran concurrently with tests creating temporary files inside the source tree. No source file was changed by that attempt. The temporary files were cleaned up, the manifest was regenerated, and the **sequential** `./scripts/dry-run.sh` passed: 11,249 manifest records, patched SDK syntax/import, 30 JavaScript tests passed, one AF_UNIX bind skip, zero JavaScript failures. Release integrity checks run sequentially so the manifest sees a stable source tree.

After document finalization, run and record the final integrity and release commands below. The payload manifest includes this file, so it must be generated after edits and before building the archive.

| Command | Required result |
|---|---|
| `./bin/node scripts/integrity.mjs --write` | Regenerate manifest for the complete v2 source. |
| `./bin/node scripts/integrity.mjs --verify` | Manifest matches source. |
| `./bin/node --check vendor/node_modules/@spectrum-ts/imessage/dist/index.js` | Full patched module parses. |
| `./bin/node src/runtime.mjs --dry-run` | Patched SDK imports locally without connecting. |
| `python3 -B same-server/payload_gate.py build --source . --archive dist/photon-reply-payload-v2.tar.gz` | New archive created once, full manifest and member verification pass. |
| Independent SHA-256 of archive, manifest and gate; `verify_archive` against those pinned values | All match v2 proposed digest record. |

**Not demonstrated in this sandbox:** root-controlled gate provisioning, root-only quarantine ownership and ACLs, actual systemd chroot and bind mounts, test UID credential isolation, real AF_UNIX socket binding, effective cgroup BPF, UID nft counters, disposable network listeners, unchanged Personal Alfred connection, provider allow behavior, shared-line routing, or live native reply-target behavior. These need separately authorized OS and live tests. A timeout or connection refusal is not proof of filtering.
