# Same-server Photon reply-target test plan

**Status:** staging proposal only. No Linux identity, service, firewall rule, credential, Photon connection or live message has been created or changed. Personal Alfred stays running. This plan uses the existing copied Node/Spectrum runtime and corrected native provenance patch; it does not start Hermes or a second gateway.

## Current read-only evidence

- The host reports Ubuntu systemd 255.4; `nft` and `systemd-analyze` are present. The dedicated `photon-reply-test` account is absent.
- `/home/alfred/.hermes` is mode `0700` owned by `alfred`. The Task A staging tree is user writable and therefore **not** a suitable final service execution path.
- The Codex sandbox exposes a read-only cgroup2 mount and blocks AF_UNIX bind and nested `bwrap` namespaces. It cannot demonstrate effective systemd cgroup IP filters, Unix-socket permissions, service credentials or host firewall rules. These are mandatory OS acceptance checks, not inferred from this plan.
- `systemd-analyze security --offline=yes` is a static assessment only. Direct `systemd-analyze verify` reports `/app/bin/node` missing because it checks in the host namespace before installation. `scripts/verify-unit.mjs` rebases executable paths for parser verification in a disposable staging root. Chroot execution remains an OS acceptance gate.

## Boundary and exact layout

```text
Personal Alfred (existing alfred UID, existing Photon project and connection)
  └─ unchanged; no shared credentials, groups, mounts or service controls

photon-reply-test UID (no login, no alfred/Gateway/docker/sudo groups)
  └─ photon-reply-test@initial or @reconnect systemd unit, never both
       ├─ RootDirectory=/srv/photon-reply-test/root
       │    └─ /app: root-owned, read-only copy of this runtime
       ├─ /run/credentials/<unit>: systemd-delivered test-only files
       ├─ /run/photon-reply-test-<phase>: 0700 command socket
       └─ /var/lib/photon-reply-test/<phase>: 0700 bounded results
```

The staged [unit](same-server/photon-reply-test@.service) uses a static unprivileged UID, `RootDirectory`, no capabilities, `NoNewPrivileges`, a read-only OS view, private devices/tmp/IPC, restricted address families, `IPAddressDeny=any` and no default `IPAddressAllow`. `/home`, production Hermes, Gateway, Obsidian, agent files, repositories, GitHub credentials and host service sockets are outside the chroot. Only `/usr` and CA certificates are read-only binds; `/lib` and `/lib64` are relative links into `/usr`. The root contains a minimal `hosts` and [NSS policy](same-server/chroot-nsswitch.conf), never host `/etc` or `/run`. The test UID must have no supplementary groups. The exact future layout is in [FILESYSTEM_PERMISSIONS.md](same-server/FILESYSTEM_PERMISSIONS.md). These claims require process-level checks after separate authorization.

The installation copy must be owned by root and not writable by `alfred` or the service UID. The reviewed payload archive, manifest and payload gate require SHA-256 approval in a separately protected root-owned record. An independent root-controlled channel supplies the reviewed gate; the installer never copies or executes a gate from staging as root. The approved gate performs a bounded, digest-checked descriptor handoff of the staging archive into root-private quarantine before extraction. The staging tree is never a root trust anchor. See [OPERATOR_CANDIDATE.md](same-server/OPERATOR_CANDIDATE.md) for the exact sequence. No source files outside Task A are patched. The unit intentionally has no `[Install]` section and `Restart=no`.

## Identity and credentials

After separate authorization, create one locked system account and group named `photon-reply-test`, with home `/nonexistent`, shell `/usr/sbin/nologin`, no supplementary groups, no sudo/polkit grants, no access to `alfred` groups, and no user service manager. Record its numeric UID for the dedicated firewall rule. Verify `id photon-reply-test` before any start. Do not change Personal Alfred's account or groups.

The proposed human-operated creation command, **only after that authorization**, is `sudo useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin photon-reply-test`. Verify the resulting UID, locked password and group list before continuing; if a user or group of that name already exists, stop and review it instead of reusing it blindly.

Store only the disposable test project's `credentials.json` and private routing `metadata.json` under `/etc/photon-reply-test/`, owned by root, mode `0400`, directory `0700`. They must not be placed in the runtime tree, environment, command line, shell history, logs or Codex output. The unit's `LoadCredential=` settings make read-only per-unit copies available in `$CREDENTIALS_DIRECTORY`; the runtime accepts that directory only with its fixed phase, result and socket paths. A systemd credential ownership/mode check under the actual service UID is required before live use. Optionally switch to `LoadCredentialEncrypted=` after a separate review. The test project ID in both files must match, and must differ from the production project ID using non-secret provider metadata.

The test UID sees only those two test credentials. Root source files remain outside the chroot. The result directory and command socket are each phase-specific. Only the dedicated UID and root can access them. The [fixed control wrapper](scripts/operator-control.mjs) runs only in phase-specific, chrooted systemd control units with a single AF_UNIX socket bind, no credentials and no IP networking. It accepts fixed tokens such as `preview-A` and `expect-direct`; it accepts no arbitrary text, message ID, credential or destination. The [results reader](scripts/read-results.mjs) runs in its own unprivileged chrooted unit with a read-only bind of one phase's state directory. It checks type, inode, link count, owner, mode, size and record grammar before showing bounded privacy-safe output; no root `tail` reads service-owned files.

## Network rule and provider inventory

The copied SDK uses `https://spectrum.photon.codes` for project/auth calls, `wss://fusor-ws.spectrum.photon.codes` for event subscription, and in shared iMessage mode `imessage.spectrum.photon.codes:443` for the gRPC client (see copied SDK `@spectrum-ts/core/dist/index.js` near lines 3049 and 3377, and `@spectrum-ts/imessage/dist/index.js` near lines 539–547). SDK environment URL overrides are cleared in the unit. Telemetry is disabled in the observer. A test-only provider metadata review must confirm the exact endpoints for this account and SDK version; unknown or changing endpoints fail closed.

Before each separately authorized session, an operator must resolve only those reviewed hostnames, record numeric IPv4/IPv6 addresses and expiry, create a chroot `/etc/hosts` with those names and numeric addresses, and add only those addresses to a reviewed `IPAddressAllow=` drop-in. The chroot `hosts: files` policy needs no DNS exception. No loopback, private, link-local, host-bridge or production IP is allowed. If DNS/IPs change, the test stops until addresses and policy are reviewed again.

The staged [nftables template](same-server/network-allowlist.nft.in) is a second layer: its renderer emits separate IPv4/IPv6 rules only for supplied numeric provider addresses, matches only the numeric test UID, permits TCP 443 to those addresses, and drops all other outbound packets for that UID. Its default output policy is accept for other users. The batch uses a uniquely named `create table`, so it fails on an existing table and never flushes other rules. Synthetic rendering passed; actual `nft -c` is blocked by this sandbox's Netlink `EPERM` and no rule has been installed. `IPAddressDeny=any` depends on cgroup eBPF support; neither it nor nft is effective evidence until separate OS tests pass. Do not allow local DNS simply by allowing `127.0.0.53`: that would also allow other loopback ports under an address-only filter. Candidate commands and targeted rollback are in [OPERATOR_CANDIDATE.md](same-server/OPERATOR_CANDIDATE.md).

## Read-only preflight and later OS acceptance

Run [same-server-preflight.sh](scripts/same-server-preflight.sh) from staging now or later. It checks software/version, cgroup metadata, account presence, protected-directory metadata, `nft` availability, and unit syntax with a disposable staging-root rebase; it reads no secret contents and changes no production state. Direct systemd verification and execution inside the chroot are separate checks. `systemd-analyze security --offline=yes photon-live-test/same-server/photon-reply-test@.service` is a static review, not an access test.

After separate authorization to install a **disposable** test identity and unit, and before any Photon credentials or live connection, independently verify all of the following using a probe service with the *same* UID, root directory, mounts and firewall rules but no Photon credentials:

| Boundary | Read-only inspection | Separately authorized disposable test and PASS condition |
|---|---|---|
| Filesystem | `id`, `stat`, `namei`, `findmnt` and `systemctl show` for the test unit and copied root; no protected file contents | `access(2)` against harmless sentinels in `/home/alfred`, Gateway, Obsidian, repo and sibling credential locations returns denied/absent; `/app` reads succeed; writes outside state/runtime dirs fail |
| Credential | Inspect only owner/mode and `LoadCredential` property; never print values | A disposable sentinel credential is readable only in `$CREDENTIALS_DIRECTORY`; source file, production credential sentinels and other unit credentials are inaccessible |
| Service control | Inspect UID groups, caps, unit namespace properties and absence of host D-Bus/systemd sockets inside root | A command targeting a **disposable** unit cannot start/stop it from the test UID; Personal Alfred is not touched |
| Cgroup IP deny | Inspect `IPAddressDeny=any` and no allow in the effective probe unit; prove cgroup eBPF attached | With nft test table absent and a separately confirmed reachable disposable listener, the probe returns `EACCES`/`EPERM` for a blocked IP. A timeout or `ECONNREFUSED` is inconclusive. |
| UID nft deny | Inspect the uniquely named test table, UID match and rule counters; use a probe-only cgroup exception for one disposable public listener | With that cgroup exception active, listener reachability confirmed from an independent identity, and nft drop counter increasing for the test UID, the test UID fails to connect while a non-test UID succeeds. A timeout alone is inconclusive. Remove exception and test table only through targeted rollback. |
| Approved allow | Inspect one reviewed temporary disposable public IP/443 exception in cgroup and UID nft sets | The test UID connects and listener records the connection; another port and local/private listener fail with relevant deny evidence. Remove disposable exception before Photon testing; actual provider allow is a separate live-authorized check. |
| Lifecycle | Inspect `Restart=no`, `RuntimeMaxSec`, phase paths and PID/cgroup | Stop and crash the disposable probe; verify cleanup, no automatic restart, no lingering socket/process, and no effect on Personal Alfred |

The [network acceptance protocol](same-server/NETWORK_ACCEPTANCE.md) records separate cgroup-deny, UID nft-deny, approved-allow, local/private-deny and Personal Alfred unaffected evidence. Any unsupported eBPF/nft feature, unexpected readable path, local connection, inherited group, credential leak, service-control success, provider endpoint change or unexplained unit warning blocks live testing. Do not work around a failed restriction by broadening the allowlist or disabling isolation.

Only after all checks pass may a root operator create `/etc/photon-reply-test/os-acceptance.ok` as a recorded acceptance marker. The unit's `AssertPathExists=` prevents startup without it. The marker is an operator attestation, not proof by itself; retain the actual test results for independent review. No OS test or marker creation is authorized by this document.

## Shared-line routing and six-case session

Before starting a live session, use non-secret provider metadata to verify separate account/project/line, a sender identity distinct from production, and the exact `(test sender, shared test line)` route bound only to the test project. The runtime's private metadata requires those assertions. After connection, send only the fixed `LAB ROUTE <nonce>` preflight from the test sender. Confirm it appears in the test project and independently confirm **no production delivery** before the operator issues `route-ok`. Account separation by itself is insufficient. If either check is unavailable or ambiguous, stop without previews.

The later human-operated commands, after live authorization, are below. Each control unit has `Requisite=`, so invoking it cannot start an observer. The result unit reads only fixed files inside the chroot and emits bounded validated records to its own journal; inspect only that unit's output. The root operator must verify the intended observer phase is already active, and must manually confirm routing before `route-ok`.

```bash
sudo systemctl start photon-reply-test@initial.service
sudo systemctl start photon-reply-results@initial.service
result_invocation=$(systemctl show -p InvocationID --value photon-reply-results@initial.service)
test -n "$result_invocation"
journalctl --no-pager -q _SYSTEMD_INVOCATION_ID="$result_invocation"
sudo systemctl start photon-reply-control-initial@route-ok.service
sudo systemctl start photon-reply-control-initial@preview-A.service
sudo systemctl start photon-reply-control-initial@expect-direct.service
sudo systemctl start photon-reply-results@initial.service
result_invocation=$(systemctl show -p InvocationID --value photon-reply-results@initial.service)
test -n "$result_invocation"
journalctl --no-pager -q _SYSTEMD_INVOCATION_ID="$result_invocation"
sudo systemctl stop photon-reply-test@initial.service
sudo systemctl start photon-reply-test@reconnect.service
sudo systemctl start photon-reply-results@reconnect.service
result_invocation=$(systemctl show -p InvocationID --value photon-reply-results@reconnect.service)
test -n "$result_invocation"
journalctl --no-pager -q _SYSTEMD_INVOCATION_ID="$result_invocation"
sudo systemctl start photon-reply-control-reconnect@route-ok.service
sudo systemctl start photon-reply-control-reconnect@preview-E.service
sudo systemctl start photon-reply-control-reconnect@expect-reconnect.service
sudo systemctl stop photon-reply-test@reconnect.service
```

These are instructions for a separately approved operator, **not commands executed now**. Issue the remaining initial-phase `expect-unthreaded`, `preview-B`, `preview-C`, `expect-unrelated`, `expect-overlap-c`, `expect-overlap-b`, `preview-D` and `expect-delayed` instances in the order and with the human messages described in the six-case table in `README.md`. Repeat the fresh routing preflight before `route-ok` in **each** phase. Stop the initial instance and verify its PID/socket are gone before starting reconnect. The service is never enabled at boot. The runtime stores native outbound IDs only in memory, logs bounded equality outcomes, and makes no automatic replies, Gateway calls or read receipts. If a send is uncertain, stop and discard the run. Review results privately; revoke test credentials and remove the test route after the experiment. Account/unit/firewall deletion requires its own authorization and must target only test artifacts.

## Remaining human approvals and blockers

1. Independently review and approve the exact payload archive, manifest and payload gate digests in a root-protected record; then approve creation of the dedicated Linux UID and root-owned chroot/credential paths and installation of the staged unit. None exists yet.
2. Approve UID-specific nft and reviewed numeric provider allowlist; obtain complete test-project endpoint metadata and prove kernel enforcement with disposable tests.
3. Approve the disposable OS isolation tests and independently review their evidence before creating the acceptance marker.
4. Approve use of the separate Photon account/line and test-only credentials; verify provider `(sender,line)` routing and a way to check absence of production delivery.
5. Separately authorize the actual Photon connection and six live messages. This plan grants no live-test or production approval.

Official systemd 255 behavior referenced for [root directories, mounts and credentials](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml) and [IP address filtering](https://github.com/systemd/systemd/blob/v255/man/systemd.resource-control.xml) must be confirmed on this host by the OS acceptance tests above.
