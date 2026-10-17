# Offline preparation results — 2026-10-14 UTC

All commands below were run without project credentials, a Photon connection, a live message or a Gateway action.

| Check | Exact command | Result |
|---|---|---|
| Synthetic protocol and private loader | `photon-live-test/bin/node --test --test-isolation=none --test-reporter=tap photon-live-test/tests/*.test.mjs` | 16 passed, 0 failed, 0 skipped |
| Full copied Spectrum module parse | `photon-live-test/bin/node --check photon-live-test/vendor/node_modules/@spectrum-ts/imessage/dist/index.js` | Exit 0 |
| SDK runtime import/no connection | `photon-live-test/bin/node photon-live-test/src/runtime.mjs --dry-run` | PASS: copied SDK import, local path, no connection |
| Corrected patch installed in copied SDK | `git apply --reverse --check -p5 ../../patches/spectrum-native-reply-provenance.proposed.patch` from `photon-live-test/vendor` | Exit 0 |
| Manifest verification | `photon-live-test/bin/node photon-live-test/scripts/integrity.mjs --verify` | PASS; per-file inventory including pinned Node, lockfile, packages, source and templates |
| Filesystem namespace probe | `photon-live-test/scripts/isolation-probe.sh` | BLOCKED: current outer sandbox denies nested user namespace. No elevation attempted. Must pass on a separately authorized disposable host/VM. |

Source checksum evidence:

| Item | SHA-256 |
|---|---|
| Installed original `@spectrum-ts/imessage/dist/index.js` (read only) | `2f7e13c432ad4e84f96b76eb3d59062d70d3d7e46737a7e15198a47ecda6ef24` |
| Copied patched module | `9faf0be1530dde1e2f80b580d12377a1fa6b0995c3595794648237a2c8f241ee` |
| Corrected proposed patch | `62d280e45e66b6880bf4e37d46aafbbf7cd4340368c5f85e6821f62c3cc62552` |

The pinned SDK was copied from the installed sidecar into `vendor/node_modules`; the patch was applied only to that copy. The original installed module retained its known SHA-256. No live routing separation, provider reply behavior, or network isolation has been verified by these synthetic checks.

Live blockers: an independently reviewed disposable host/VM egress boundary and successful `bwrap` probe; private test-only credentials; provider evidence for the exact shared-line/sender route and production exclusion; and separate human authorization for live connection and messages. The live launcher refuses to run on a host with `/home/alfred/.hermes` or without the explicit network-boundary attestation flag. That flag is an operator assertion, not technical proof of egress isolation.

## Same-server staging update — 2026-10-14 UTC

The later same-server proposal adds `SAME_SERVER_TEST_PLAN.md`, a static systemd unit template, a UID-specific nftables template, systemd credential/runtime path validation and an operator-only Unix command socket. The VM-oriented launcher and its earlier 16-test result remain historical evidence.

- `photon-live-test/bin/node --test --test-isolation=none --test-reporter=tap photon-live-test/tests/*.test.mjs`: **18 passed, 0 failed, 1 skipped**. The skipped test is the Unix command socket bind; this Codex sandbox returns `EPERM`. It must run in the separately authorized systemd OS acceptance environment.
- `photon-live-test/bin/node photon-live-test/src/runtime.mjs --dry-run`: copied SDK import PASS; no connection.
- `systemd-analyze security --offline=yes --no-pager photon-live-test/same-server/photon-reply-test@.service`: static exposure score **2.6**, not an enforcement test.
- `systemd-analyze verify photon-live-test/same-server/photon-reply-test@.service`: **inconclusive/exit 1** because `/app/bin/node` does not exist until the future isolated root is installed. No installation was attempted.
- A sample `nft -c -f -` syntax check with documentation IPs was **blocked** by this sandbox: Netlink socket initialization returned `EPERM`. No firewall rule was applied. A separately authorized operator must syntax-check the rendered rule on the host before installation.
- The service UID, credential handoff, chroot mounts, cgroup eBPF IP filter, nftables rule and shared-line route remain untested and uninstalled.

## Same-server hardening validation — 2026-10-14 UTC

The earlier results above remain historical. This hardening pass changed only `photon-live-test/` staging files and did not create a Linux account, install a unit, modify nftables, provision credentials or connect to Photon.

| Exact command from `photon-live-test/` | Result |
|---|---|
| `./bin/node --test --test-isolation=none --test-reporter=tap tests/*.test.mjs` | 27 cases: **26 passed, 0 failed, 1 skipped**. The AF_UNIX bind case remains skipped because this sandbox returns `EPERM`. |
| `./bin/node scripts/verify-unit.mjs` | PASS: systemd 255 parser accepted both templates with a disposable root and rebased executable paths. Direct verification of uninstalled `/app/bin/node` remains inconclusive. |
| `./bin/node scripts/check-chroot-layout.mjs` | PASS: ELF interpreter and 8 linked Node libraries resolve through reviewed read-only `/usr` bind on this host. Actual chroot execution pending. |
| `./bin/node src/runtime.mjs --dry-run` | PASS: copied SDK imports locally; no connection. |
| `./bin/node --check src/runtime.mjs` and `./bin/node --check scripts/firewall-transaction.mjs` | Both exit 0. |
| `systemd-analyze security --offline=yes --no-pager same-server/photon-reply-test@.service` | Static score 2.6; no OS enforcement conclusion. |
| `nft -c -f same-server/network-allowlist.nft.in` | Inconclusive: Netlink `EPERM` in this sandbox. The template is not rendered and actual syntax must be checked on the separately authorized host with reviewed numeric IPs. No rule was installed. |

The new tests exercise missing credentials and manifest, mismatched project binding, broad credential modes, wrong runtime paths, direct staging startup refusal, IPv4-only/IPv6-only/dual-stack rendering, local-address rejection, duplicate table refusal, simulated interruption after firewall commit and targeted rollback. The simulated transaction does **not** prove real nft behavior. No test account, chroot, systemd credential mount, socket bind, UID ownership, cgroup BPF filter, firewall rule or network listener has been run at OS level.

Required independent OS acceptance: install a root-owned copy and prove `alfred`/service UID cannot write it; check ACLs and symlink resolution; run `ExecStartPre`/`ExecStart` in the actual chroot with sentinel credentials; verify `AssertPathExists` failures; bind the AF_UNIX socket under `SocketBindDeny=any`; run reachable disposable positive and negative network listeners and inspect effective cgroup/nft counters; test crash/stop cleanup and rollback; verify no production path/service/control access. The shared-line routing check and six live Photon cases remain separately authorized future work.

## Installer trust-boundary correction — 2026-10-14 UTC

The earlier copy-first procedure is superseded by [OPERATOR_CANDIDATE.md](same-server/OPERATOR_CANDIDATE.md). The operator must independently approve the compressed payload, internal manifest and payload-gate hashes outside staging. A root-private copy is checked with trusted host `sha256sum` before the hash-approved gate runs. The gate rejects unlisted or modified files, path traversal, external symlinks, hard links, special files, unexpected owners, modes and ACLs. Copied Node runs only under the test UID in a transient network-disabled systemd chroot; the root uses host tools for installation and nft. This sequence has **not** been installed or exercised as root on the host.

| Exact staging command from `photon-live-test/` | Result |
|---|---|
| `python3 -B -m unittest -v tests/test_payload_gate.py` | 8 passed, 0 failed; includes modified payload, forged manifest, symlink swap/escape, path traversal, hard link, special file, wrong owner/mode, ACL metadata, interrupted/partial install and staging mutation. |
| `./bin/node --test --test-isolation=none --test-reporter=tap tests/*.test.mjs` | 26 passed, 0 failed, 1 skipped. The AF_UNIX bind case remains sandbox-blocked. |
| `./bin/node scripts/verify-unit.mjs` | PASS for static systemd parser with rebased executables; no installed-unit proof. |
| `./bin/node scripts/check-chroot-layout.mjs` | PASS for copied Node ELF and 8 linked libraries; no chroot execution proof. |
| `python3 -B same-server/payload_gate.py build --source . --archive dist/photon-reply-payload.tar.gz` | PASS: scanned, packed and reverified 11,241 manifest entries. The first attempt was interrupted after identifying an inefficient gzip seek pattern in the offline verifier; physical-order streaming was added and the build completed. |
| `payload_gate.verify_archive(..., extract=True, destination="dist/extract-check")` | PASS: full archive extraction of 11,241 entries into disposable staging, with no root privileges. |
| Extracted copy: `bin/node scripts/integrity.mjs --verify`, `bin/node src/runtime.mjs --dry-run`, `bin/node --check vendor/node_modules/@spectrum-ts/imessage/dist/index.js` | All PASS; 11,241 file hashes verified, copied SDK imported locally and full patched module parsed. Disposable extraction removed afterward. |

The pinned archive and proposed digests are generated only after this document and the remaining staging files are finalized. Their values are recorded in the excluded `dist/PROPOSED_DIGESTS.txt` and require independent review before a protected approval record may be created. The current sandbox cannot prove the transient systemd confinement, root ownership/ACLs, nft transaction, credential handoff, Unix socket bind or disposable listener behavior. These remain test-only OS acceptance blockers. No Photon login or message was attempted.
