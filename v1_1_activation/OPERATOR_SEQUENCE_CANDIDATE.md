# V1.1 controlled activation: operator sequence candidate

**Preparation only; do not execute this sequence yet.** `OPERATOR_MINIMAL_MIGRATION.md` now contains the concrete unit and command candidate for steps 4–10. Host process and OS acceptance checks remain pending. No live source, service, credential, registry or Gateway change was made while preparing this file.

## Pinned inputs and observed host state

| Input | SHA-256 / source pin |
| --- | --- |
| `v1_1a/patches/gateway-task-filing.proposed.patch` | `74b747b5ed672fe7b7fdf97d3fed40c6493dd896693ea48cca53232f5dbe5604` |
| `v1_1b/patches/hermes-photon-gateway-intake.proposed.patch` | `876a1042b27b47b9e6080ead2004b96e025f6b83fc1c728690533f6c24ae178a` |
| `patches/spectrum-native-reply-provenance.proposed.patch` | `62d280e45e66b6880bf4e37d46aafbbf7cd4340368c5f85e6821f62c3cc62552` |
| Gateway checkout | `0086db5f2c9a41b66161559a11056e4d14138cf9` |
| Hermes checkout | `26610b09a5c4aead8d8dfb276ea33decf0d7fa46` |

The Gateway patch changes `.dev/bin/taskspec.py`, `.dev/bin/intake.py` and adds `.dev/task-id-reservations.txt`. The Hermes patch changes `gateway/session_context.py`, `gateway/run.py`, `gateway/run_turn.py`, the Photon adapter, `sidecar/index.mjs`, and adds `development-observe.mjs` and `restricted-media.mjs`. The Spectrum patch changes the pinned SDK's `dist/index.js` and `dist/index.d.ts`. Separately staged V1.1b files are `trusted_intake.py`, `plugin/__init__.py`, `plugin/plugin.yaml` and `config.template.json`. Use these exact reviewed inputs; do not rebuild Photon or install the old broad broker/test-runtime packages.

Read-only metadata shows `/home/alfred/.config/systemd/user/hermes-gateway.service` runs Hermes under the user manager as UID `alfred` (1000), with no whole-process filesystem denial. The protected Gateway checkout `/home/alfred/Git/alfred` and state `/home/alfred/Alfred/gateway` are also owned by `alfred` and mode `0700`. No reviewed distinct sidecar/gate service identities were identified. The bound inbox `/home/alfred/Alfred/projects/hermes-requests/inbox` does not yet exist. The protected registry contains only project `alfred`, not `dev-001`. The clean main worktree `/home/alfred/alfred-development-lab/repo` is the isolated no-remote lab repository; its separate `worktrees/dev-001` branch is dirty and must not be used for first filing. The main worktree lacks `.dev/tasks` and needs the approved fixture initialization.

## Ordered procedure and gates

0. **Approval stop.** Obtain every decision in `ADR_MINIMUM_PROPOSED.md` and a reviewed, exact whole-process migration/rollback artifact. Do not patch or stop Personal Alfred before that artifact proves Hermes cannot access Gateway source/state or write the bound inbox. The current same-UID user service does not meet this condition.

1. **Verify pins and clean sources (read-only).** From `/home/alfred/alfred-development-lab/milestone2/task-a`:

   ```sh
   sha256sum v1_1a/patches/gateway-task-filing.proposed.patch v1_1b/patches/hermes-photon-gateway-intake.proposed.patch patches/spectrum-native-reply-provenance.proposed.patch
   git -C /home/alfred/Git/alfred rev-parse HEAD
   git -C /home/alfred/Git/alfred status --short
   git -C /home/alfred/.hermes/hermes-agent rev-parse HEAD
   git -C /home/alfred/.hermes/hermes-agent status --short
   git -C /home/alfred/alfred-development-lab/repo status --short
   git -C /home/alfred/alfred-development-lab/repo remote -v
   ```

   Require the hashes and commits in the table, clean source checkouts, clean lab main worktree and no lab remote. The operator must independently protect the approved digests; a manifest in writable staging alone is not an approval record.

2. **Verify patch applicability (read-only).** From the same directory:

   ```sh
   git -C /home/alfred/Git/alfred apply --check /home/alfred/alfred-development-lab/milestone2/task-a/v1_1a/patches/gateway-task-filing.proposed.patch
   git -C /home/alfred/.hermes/hermes-agent apply --check /home/alfred/alfred-development-lab/milestone2/task-a/v1_1b/patches/hermes-photon-gateway-intake.proposed.patch
   git -C /home/alfred/.hermes/hermes-agent apply --check /home/alfred/alfred-development-lab/milestone2/task-a/patches/spectrum-native-reply-provenance.proposed.patch
   ```

   All three checks returned zero during preparation. A mismatch stops the installation; do not apply with fuzz.

3. **Inspect actual service state and backup locations (read-only).** The operator must run on the host, outside this Codex sandbox:

   ```sh
   systemctl --user status hermes-gateway.service --no-pager
   systemctl --user cat hermes-gateway.service
   stat -c '%n %F %U:%G %a' /home/alfred/.hermes /home/alfred/Alfred/gateway /home/alfred/Git/alfred
   ```

   Codex could read the unit file but could not connect to either systemd bus (`Operation not permitted`), so active service state remains unverified. The operator records the current unit, installed source hashes and credential locations in a protected backup **without printing secret contents**.

4. **Prepare rollback and isolate authority before cutover.** Under the separately reviewed service/credential migration artifact, create a protected backup of the current Hermes source, user unit, configuration, Photon SDK and Gateway source/registry. Use the minimum split in `MINIMAL_SERVICE_ISOLATION.md`: two new stable service UIDs for the Hermes requester and Photon sidecar, with the existing `alfred` UID for the protected intake gate and Gateway. Install root-controlled reviewed code/runtime copies and fixed credentials without placing Photon project credentials or the control token in Hermes. Deny Hermes the Gateway checkout/state, registry, lab task repo and bound inbox. Give the gate only fixed inbox write, journal read, sidecar preview send and its Unix socket. Confirm the Gateway can read newly published `0640` envelopes. **No command may run staging Node or JavaScript as root.** Stop if these denials cannot be demonstrated.

5. **Stop the old connection, then install reviewed code.** Stop `hermes-gateway.service` and verify its spawned Photon sidecar has exited **before** altering its source or starting a replacement. Apply the approved V1.1a patch to the Gateway source, V1.1b patch to the Hermes source and the corrected native Spectrum patch to that same sidecar's pinned dependency. Install `trusted_intake.py` and the two-file Hermes plugin under the approved root-controlled runtime layout. Initialize `.dev/tasks` in the clean lab main worktree and add exactly one approved `dev-001` row to the protected Gateway registry, with `company: alfred`, `permissions.hermes_requests: true` and `local_path: /home/alfred/alfred-development-lab/repo`. No GitHub remote, developer role or execution grant is added. Re-run the focused regressions before any service start. If any check fails, restore the backup and restart only the original service.

6. **Single-connection cutover.** Start the protected sidecar with the same existing Photon project/line and patched SDK. Start the protected gate, then start Hermes in external-sidecar mode with the reviewed plugin and ordinary media spool. Never run old and new sidecars simultaneously. The new Hermes process gets the shared ordinary messaging token, not the Photon project credentials or separate control token. Verify ordinary conversation before enabling Gateway pickup. If it fails, invoke rollback immediately.

7. **Mandatory host boundary checks.** Record UID and `SO_PEERCRED` results for both gate clients; prove Hermes cannot call `observe`, read gate/sidecar credentials, read Gateway state or write/list the inbox, and cannot call protected `/shutdown` or arbitrary-path `/send-attachment`. In an approved disposable fixture, prove the gate alone can atomically publish a Gateway-readable envelope; leave the real inbox empty until step 9. Verify normal Photon text, photo, voice and document send/receive through the one connection and no Evidence Bridge regression. Test a direct owner reply against the sidecar's outbound preview ID; prove unthreaded, wrong-target and thread-fallback replies do not supply an equal native `replyTargetGuid`, and ordinary replies expose `nativeIsForward=false`. Keep Gateway pickup disabled until this evidence passes.

8. **Authorize one lab filing test.** Only after the ADR 0011 R-ID hold is explicitly lifted for this isolated lab and `/ship`/other writers are excluded, permit one controlled `gateway.py run-once` pickup against the bound inbox and approved `dev-001` registry entry. No timer, CTO scheduler, developer run or GitHub tool is enabled.

9. **Live acceptance (exactly one request).** The authenticated owner texts a natural-language software request to Personal Alfred. Alfred drafts it; the protected gate sends a complete preview to that same owner DM. Check that no inbox envelope or task exists before confirmation. The owner directly replies `Yes, go ahead` to **that** preview within five minutes. The gate writes one `alfred.devreq/1` envelope; the Gateway files exactly one canonical `proposed` spec in the lab repository's `.dev/tasks`, journal outcome `filed`, requester source `hermes`, no approval or execution state. Alfred reports the real task ID. A second owner direct reply to the same preview must not create a second task; synthetic duplicate-event tests already cover replay of one SDK event ID. Stop on wrong sender, wrong target, missing native fields, unreadable inbox, duplicate ID, non-proposed status or messaging regression.

10. **Close or roll back.** Preserve privacy-safe evidence (hashes, UIDs, equality booleans, request/task IDs and test outcomes; no message contents or credentials). Leave the pilot disabled unless the operator has separate authorization for continued operation. On failure, stop protected gate and new Hermes/sidecar services, restore the protected backup of the old Hermes code, SDK, user unit and configuration, and start the original `hermes-gateway.service` **only after** the new sidecar is stopped. Restore the Gateway source/registry from backup while Gateway pickup is disabled. Retain the Gateway journal and any already filed task for audit; never delete a canonical task to disguise a partial acceptance. Remove only test-specific units, identities, socket/runtime paths and inbox permissions after verifying no active pilot process uses them. Confirm ordinary Photon messages work through the original single connection.

## Installation blocker

The reviewed V1.1b code requires distinct process UIDs and whole-process denial of protected Gateway paths. The current Hermes user unit runs as the same UID that owns those paths. `OPERATOR_MINIMAL_MIGRATION.md` and its three staged units supply a concrete **candidate** for two new service UIDs, credential separation and rollback. The host operator must still prove the active old service/sidecar, source and credential preflight, new-home behavior, socket peer credentials, filesystem denial and ordinary Photon compatibility. Do not treat unit syntax, source-patch applicability or synthetic tests as permission to cut over. No Photon or Gateway feature development is needed.
