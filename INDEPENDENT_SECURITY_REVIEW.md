# Task A independent security review — procedure, not a passing result

The v0.1.4 corrective workspace remains incomplete; no v0.1.4 release
archive exists. The current independent checklist and unresolved provider,
binding, cross-UID and regression gates are in `V014_CORRECTIVE_STATUS.md`.
The v0.1.3 checklist below is retained as historical scope.

**Not executed:** privileged UID/group, DAC/ACL, actual systemd unit, namespace, coding-agent escape, real Photon sidecar split, live evidence-reader and production compatibility tests. The proposed split is a patch plus a synthetic staging front, not an applied or authenticated live Photon deployment. This sandbox also denied Unix socket bind/send, so cross-UID IPC tests remain pending. Passing tests do not prove Linux isolation.

## v0.1.3 review focus

Verify the archive and each SHA256SUMS entry, then apply the proposed patch
only to an isolated copy of the pinned installed Hermes bytes. Exercise the
actual `task_a.service` entry point with socket activation, `LoadCredential`
and the intended separate UIDs. Inspect inherited file descriptors, process
environments, one Spectrum connection, socket owner/group/modes and the
create-only inbox ACL. Confirm Gateway can read new files while the broker
cannot list unrelated inbox names. Fault injection must cover a sidecar crash
before/after spool fsync, broker journal fsync, `/ack`, SDK read receipt,
Hermes dispatch, handle reservation and uncertain outbound send. Measure SDK
redelivery after a crash before spool fsync; that guarantee is unverified.
Run a 32-client slow-header/body soak and verify the five-second absolute
request deadline, process memory and bounded audit handling. Check that
sidecar or SDK diagnostics cannot leak credentials or raw principals via
system logs. The full legacy and patched Hermes Photon regression suites
remain acceptance gates; the current sandbox's broad run failed with an
incomplete async/Node harness and a thread timeout.

An independent reviewer must work on a separately authorized disposable host whose paths and accounts mirror the candidate manifest. Do not use the real Gateway repository, journal, approvals, credentials or PAUSE/STOP as fixtures. Capture command, UID/GID, unit property, expected denial, actual errno, timestamp and artifact hash without printing secret values.

## Required measurements and negative probes

1. **Identity and unit:** confirm assigned UIDs are collision-free; inspect `/proc/<pid>/status` for Hermes, every plugin/child, broker and lab Gateway. Hermes supplementary groups must be exactly GID 978; broker and lab Gateway have none. Inspect actual `systemctl show` restrictions, cgroups, mount namespace and process ancestry. Prove no old UID-1000 user unit or child remains concurrently, and no UID-31012 linger/user manager can spawn an unconfined service.
2. **Protected files:** from the running Hermes service, an in-process plugin and a local terminal child, attempt `open(O_RDONLY)` and `open(O_WRONLY)` on harmless sentinel files at mirrored real-Gateway source, registry, task spec, journal, PAUSE/STOP, approval, publisher, operator credential and broker-key paths. Require kernel `EACCES` or `EPERM`. Repeat for the broker against lab journal/specs and for the lab Gateway against real paths. Prove Hermes cannot create a file in the bound lab inbox; broker can create only there and cannot list/read journal state.
3. **Alternate authority:** probe passwordless sudo, setuid/su, both user-manager buses, system-manager control, `systemd-run`, Docker/LXD sockets and local APIs, `ptrace`/`/proc`, inherited descriptors, local TCP/Unix sockets, symlink/hardlink/path traversal and mount namespace changes. A denied executable name is insufficient; any code Hermes can run must remain unable to write protected Gateway state or call a privileged mutation service.
4. **Coding agents and imports:** test original Claude/Codex launchers, direct binaries, module entry points, copied/downloaded replacements, plugin import hooks and shell/Python commands from the real Hermes unit. Their presence must confer no Gateway, operator, GitHub, approval or publisher access. Do not make Codex an Alfred runtime component.
5. **Photon trust:** verify the broker, rather than Hermes, owns the authenticated Photon connection and receives the original SDK event before Hermes' phone/space fallback. Confirm no Photon `auth.json`, project credential, sidecar token or stale runtime token record is copied into Hermes state or environment. With a real test principal in an isolated account, reject absent/mismatched `sender.id`, forged sender in model args/kwargs, Company Mastermind output, group/bot/internal turns, stale/duplicate events and socket callers outside the sidecar UID. Protect principal IDs and tokens in review output. A sidecar compromise is a trusted-component compromise because sidecar and broker share UID 31011 and inbox write access; review and harden that code accordingly.
   **Staged mitigation to examine:** `patches/photon-secure-front.proposed.patch` removes the sidecar path route, moves its full control API to a private `0600` Unix socket, and makes the adapter use only the restricted front. Verify the actual patch bytes, no surviving alternate path/media/URL/control route reachable from Hermes, no leaked bearer token or project credentials in Hermes state or environment, and kernel denial on the private socket. The restricted front must accept only bounded handle-bound text replies and lab envelope submissions. Test every sidecar endpoint and local network effect. The proposal is not an acceptance result.
6. **Source and runtime:** verify root-controlled remote provenance and full approved commit, clean tree, SHA-256 manifest, root ownership, no auto-sync from UID-1000 source, no writable plugin/config replacement under the Hermes state tree, and checksum-verified rollback. Confirm the lab registry contains only `alfred`/`dev-001` and a repository with no remote/CI; no real state or credential is copied.
7. **Compatibility:** run the actual root-managed units and test normal Photon messaging, gateway restart/recovery, both Evidence Bridge Tool Search entries and handlers, evidence freshness, and Kanban read-only reporting. Check that no protected development execution, grant, approval, GitHub action or deployment occurs from Task A transport.

**Acceptance rule:** unresolved sidecar control-token/file-path reachability, any successful bypass, unsupported systemd directive, unsafe mutable-plugin mount, missing original-event provenance, credential migration ambiguity, sidecar/Hermes incompatibility, failed Evidence Bridge tool, or unverified denial blocks Task A acceptance and Task B start. The reviewer must also measure socket owner/group/mode, `SO_PEERCRED`, one SDK connection, event-feed restart/replay, and the disabled attachment behavior under separate UIDs. The independent reviewer must sign measured results in writing; static and unprivileged tests are insufficient.
