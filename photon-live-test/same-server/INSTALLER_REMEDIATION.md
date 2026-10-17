# Photon same-server installer remediation candidate v2

**Status:** staging only. No OS installation, Photon connection, credential access, firewall change or production service action has occurred. This candidate does not authorize any of those actions.

## Trust model and changes

| Finding | Staging correction | Remaining acceptance |
|---|---|---|
| H1 root copy race and unsafe file types | `payload_gate.py` performs a bounded descriptor handoff from the single pinned archive into root-private quarantine after checking owner/mode/type/link count and before verifying its independently approved complete digest. It rejects special files, symlinks, hard links, traversal, unapproved content, ACL metadata and resource overruns. The installer executes only a separately provisioned root-controlled gate after its protected hash is checked. Extraction has a marker only after file/directory fsync and final checks. | Independent reviewer must provision and verify the gate and approval record outside writable staging; run authorized root/OS tests and inspect the copied tree. |
| H2 unconfined control commands | Host `runuser` procedure and legacy control client are removed from v2. Two phase-specific, chrooted systemd templates call `operator-control.mjs` with one fixed command token and one fixed socket bind. `Requisite=` prevents control from starting an observer. No credentials or IP access. | Start/stop and effective mount/socket checks under an authorized disposable test UID. |
| H3 root log-path read | `photon-reply-results@.service` runs `read-results.mjs` as the test UID in a chroot with a read-only bind of one phase directory. It opens fixed files with `O_NOFOLLOW|O_NONBLOCK`, checks inode, owner, mode, link count, bound and privacy-safe schema, and emits only validated records. No root `tail`. | Verify actual StateDirectory binding, journal access, symlink denial and test UID permissions on the installed host. |
| M1 network probe/evidence | Oneshot probe now uses `TimeoutStartSec=15s`. Its classifier treats timeout/refusal as inconclusive. `NETWORK_ACCEPTANCE.md` requires separate cgroup-deny, UID nft-deny, approved-allow, local/private-deny and Personal Alfred unaffected observations. | Disposable listeners, effective cgroup eBPF, nft counters, provider endpoint allowance, and unchanged Personal Alfred all need separately authorized OS tests. |

The observer, native `replyTargetGuid`/`threadOriginatorGuid` separation, disposable test project, shared line, six-case protocol, Gateway architecture and Evidence Bridge are unchanged. The protected root gate and approval record must come from an independently controlled channel. A staging digest suggestion is never the approval authority.

## Failure and rollback rules

Missing protected gate, approval, archive, OS marker, credentials or test UID fails closed. The handoff creates `payload.tar.gz` with `O_EXCL`, removes it on mismatch/interruption and fsyncs its private parent on acceptance. A partial extraction has no `payload.ok` and cannot be installed; do not retry over it. Stop at any unexpected source owner/mode, archive member type, link, path, ACL, hash, quota or timeout. An uncertain preview must not be retried. The exact targeted host rollback and partial-state inventory are in [OPERATOR_CANDIDATE.md](OPERATOR_CANDIDATE.md). Only the uniquely named test nft table and test units are eligible for rollback; no existing ruleset or Personal Alfred unit is modified.

## Independent review checklist

1. Recalculate the v2 archive SHA-256, payload `MANIFEST.sha256`, and gate SHA-256 independently; inspect the archive inventory and compressed size. Do not copy the proposed digests into the protected record without review.
2. Verify the independently supplied gate is root controlled before execution. Trace `bounded_handoff` and `verify_archive`, including owner/mode/ACL checks, quotas, interruption handling, no-follow opens and `payload.ok` creation.
3. Inspect all five systemd templates and effective OS properties. Confirm no host `runuser`, root `tail`, copied Node as root, broad `/run` bind, production credential bind or automatic observer startup remains in the operator path.
4. Run the staging tests and independently authorize disposable OS acceptance before writing `os-acceptance.ok`. Live Photon permission remains separate.
