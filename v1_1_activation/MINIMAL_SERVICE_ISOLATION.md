# V1.1 minimal same-server service isolation

Status: **design note**. The concrete candidate units and commands are in `OPERATOR_MINIMAL_MIGRATION.md`; host process and OS acceptance checks remain pending. This does not authorize service changes or filing.

## Observed boundary

- Ubuntu systemd is 255 with ACL and seccomp support. The installed Hermes user unit is `/home/alfred/.config/systemd/user/hermes-gateway.service`. It starts Hermes as `alfred` (UID 1000) from `/home/alfred/.hermes` and has no whole-process restriction on Gateway paths. Its adapter starts the current Photon sidecar as a child.
- `/home/alfred/Git/alfred` and `/home/alfred/Alfred/gateway` are owned by `alfred` and mode `0700`; the protected registry is `0600`. Thus Hermes presently has the same filesystem authority as Gateway. The bound inbox does not yet exist.
- Existing `alfreddev`, `alfredexec`, and `alfredqa` are execution/workforce identities, and the memory/Obsidian identities own other services. Reusing them for Hermes or Photon would merge unrelated authority. There is no existing dedicated requester or Photon account. The existing `alfredevidencero` group is a read-only Evidence Bridge grant, not an intake IPC group.
- The staged gate checks three distinct effective UIDs: itself, Photon sidecar, and Hermes (`v1_1b/trusted_intake.py:483-523`). It authorizes SDK observations only from the sidecar UID and drafts/status only from the Hermes UID (`:108-124`). Its socket is mode `0660`; its parent must belong to the gate UID and be inaccessible to group/other writers. The gate publishes with file and directory fsync plus no-replace rename (`:407-455`).

## Minimum proposed split

| Process | UID | Access required |
| --- | --- | --- |
| Trusted Gateway and intake gate | existing `alfred` | Existing Gateway code/state; fixed bound inbox; gate config `0600`; socket parent under `/run` |
| Hermes requester | **new stable unprivileged UID** `alfredmsg` | Sanitized Hermes home, ordinary sidecar send token, intake socket, own media spool, read-only Evidence Bridge |
| Existing Photon sidecar, moved out of the Hermes cgroup | **new stable unprivileged UID** `alfredphoton` | Pinned sidecar/SDK copy, Photon project credential, separate control token, intake socket, read access only to the Hermes media spool |

This needs **two** new identities because the reviewed gate refuses a shared UID, and the present `alfred` UID already owns Gateway authority. A transient `DynamicUser` is unsuitable: `sidecar_uid` and `hermes_uid` are pinned in gate configuration and `PHOTON_HERMES_UID` is pinned in the sidecar. Do not add either new UID to `alfred`, `alfreddevipc`, `alfredauthipc`, or an execution group. The two UIDs need no shell, sudo, service-control permission, repository write access, or Gateway credential.

Use system systemd units with explicit `User=` for the three processes, `NoNewPrivileges=yes`, a read-only system tree and narrowly listed writable runtime/home paths. The Hermes and sidecar units use `ProtectHome=read-only` so their new UIDs can execute the existing launcher, Python/Node binaries and SDK under `/home/alfred/.hermes`, while writing state only under `/var/lib`. The gate needs its fixed Gateway paths and a narrow inbox write grant. UID separation supplies the primary Gateway denial. Existing execution services remain untouched.

Keep the gate as `alfred` so it retains its existing protected Gateway access. Give the two clients only socket access through POSIX ACLs on a gate-owned `0700` runtime directory and its socket; the gate's `0660` chmod must leave both named-user ACL entries effective. Keep Gateway checkout, registry, journal, approval state, dev-001 task repo, and bound inbox inaccessible to `alfredmsg`. The sidecar receives only the existing Photon project credential and its separate control token; Hermes receives neither. The shared ordinary send token is available to Hermes and the gate. The sidecar's `/shutdown` and arbitrary-path `/send-attachment` remain control-token-only; ordinary text and the reviewed restricted `/send-media` route remain available. The sidecar runs **one** existing Photon project connection after the old child exits.

Place the Hermes media spool outside protected Gateway paths, owned by `alfredmsg`, with a narrow named-user read/traverse ACL for `alfredphoton`. The reviewed spool creates `0640` files owned by Hermes; the sidecar checks that owner UID and file type before reading. Preserve the Evidence Bridge by granting `alfredmsg` only the existing `alfredevidencero` read group and copying the existing read-only status plugin to its sanitized Hermes home. Do not grant it the Gateway repository merely to make the plugin work.

## Exact read-only host preflight

Run these before approving any installation. No secret file contents are printed.

```sh
cd /home/alfred/alfred-development-lab/milestone2/task-a
systemctl --user cat hermes-gateway.service
systemctl --user status hermes-gateway.service --no-pager
getent passwd alfred alfredmsg alfredphoton
getent group alfred alfredevidencero alfreddevipc alfredauthipc
stat -c '%A %U:%G %n' /home/alfred /home/alfred/.hermes /home/alfred/Git/alfred /home/alfred/Git/alfred/registry/projects.yaml /home/alfred/Alfred/gateway
getfacl -cp /home/alfred/Git/alfred /home/alfred/Alfred/gateway
sha256sum v1_1a/patches/gateway-task-filing.proposed.patch v1_1b/patches/hermes-photon-gateway-intake.proposed.patch patches/spectrum-native-reply-provenance.proposed.patch
git -C /home/alfred/Git/alfred apply --check "$PWD/v1_1a/patches/gateway-task-filing.proposed.patch"
git -C /home/alfred/.hermes/hermes-agent apply --check "$PWD/v1_1b/patches/hermes-photon-gateway-intake.proposed.patch"
```

The first two `systemctl` calls were unavailable to Codex (`Operation not permitted`); an operator must record the active unit, its child sidecar PID and current connection before cutover. The hash approval record must be independently protected from the writable staging tree.

## Required install order and stop conditions

1. Obtain the ADR 0003 Phase 4 and ADR 0009 exception amendments already drafted in `ADR_MINIMUM_PROPOSED.md`, the V1.1a/ADR 0011 lab allocator decision, and a separate change approval for two service UIDs, unit installation, secret migration and restart. Approve the exact reviewed patch hashes independently of this writable staging copy.
2. Prepare a rollback copy of the existing unit and exact source/registry/SDK files under root-controlled storage. The old Hermes home stays untouched. Provision `alfredmsg` and `alfredphoton` as locked, stable service accounts, and install independently verified root-controlled patch copies. The new UIDs may read but not write the existing launcher/source tree; never execute scripts from writable Task A staging as root.
3. Create a **sanitized** Hermes home for `alfredmsg`. Preserve Personal Alfred's profiles, ordinary providers, message state, read-only development status plugin and needed non-Photon credentials. Remove Photon project credentials from `.env`, `auth.json` (including `credential_pool.photon`, `credential_pool.photon_project`, legacy `providers.photon`), profile overrides and inherited service environment. Verify these removals by key presence only, without disclosing values. Supply project credential solely to `alfredphoton`. This migration needs a reviewed, host-specific file inventory before an executable copy command can be safe.
4. Create the gate-owned bound inbox and gate socket directory. Configure the inbox so the `alfred` gate can create and read `0640` envelopes and Gateway can process them, while `alfredmsg` cannot traverse it. Give both client UIDs only the gate socket ACL. Configure the media spool ACL as above. Do not grant `alfredmsg` a writable bind mount or ACL on Gateway paths.
5. Stop the old Hermes user unit and confirm its sidecar child and Photon connection have exited. Only then start the protected sidecar under `alfredphoton` using the **same** project, line and patched SDK. Start the gate under `alfred`, then Hermes under `alfredmsg` with `PHOTON_SIDECAR_EXTERNAL=true`, no sidecar autostart, the ordinary send token and reviewed intake plugin. Do not run two Photon connections concurrently.
6. Keep Gateway pickup disabled until the identity, socket, path, ordinary messaging and native reply-target checks below pass. Then follow the single `dev-001` acceptance in `OPERATOR_SEQUENCE_CANDIDATE.md`; it still requires separate authorization for real filing.

The exact **candidate** install commands and file paths are in `OPERATOR_MINIMAL_MIGRATION.md`. Their host preflight is mandatory: this sandbox could not read live systemd/process state or prove that the new UIDs can run Personal Alfred.

## Minimum host verification commands after a separately reviewed install

The installed unit names below are reserved candidate names, not evidence that units exist. Run checks as the host operator without starting Gateway pickup. Each `test` must return the indicated result; `id`/`stat` output must show three distinct UIDs.

```sh
systemctl show -p User -p Group -p MainPID alfred-photon.service alfred-development-intake.service alfred-hermes.service
systemctl status alfred-photon.service alfred-development-intake.service alfred-hermes.service --no-pager
id alfredmsg
id alfredphoton
stat -c '%A %U:%G %n' /run/alfred-development-intake /run/alfred-development-intake/intake.sock /home/alfred/Alfred/projects/hermes-requests/inbox
getfacl -cp /run/alfred-development-intake /run/alfred-development-intake/intake.sock
runuser -u alfredmsg -- test ! -r /home/alfred/Git/alfred/registry/projects.yaml
runuser -u alfredmsg -- test ! -w /home/alfred/Alfred/gateway
runuser -u alfredmsg -- test ! -w /home/alfred/Alfred/projects/hermes-requests/inbox
runuser -u alfredmsg -- test ! -r /home/alfred/Alfred/projects/hermes-requests/inbox
runuser -u alfredmsg -- test ! -w /home/alfred/alfred-development-lab/repo/.dev/tasks
```

`runuser` probes alone are necessary but insufficient: perform the same negative checks with disposable test commands **inside the actual Hermes service sandbox/cgroup**; prove the gate receives the expected `SO_PEERCRED` UIDs and rejects a direct Hermes confirmation. A disposable envelope test must show gate publication, Gateway readability, no duplicate, and no Hermes inbox access without invoking the real dispatcher. Verify native direct-reply ID matching and normal text/photo/voice/document traffic through the single live connection before enabling pickup. Verify Evidence Bridge status under `alfredmsg`.

## Targeted rollback order

After a separately approved cutover, stop the new Hermes unit, sidecar and gate in that order; verify the sidecar connection is gone before restoring the original single-connection user unit. Follow the exact candidate reverse-patch and restart commands in `OPERATOR_MINIMAL_MIGRATION.md`. Disable Gateway pickup during rollback and retain any filed task/journal record for audit. Confirm ordinary Photon messaging and Evidence Bridge through the restored unit.

## Current blocking host requirement

Review and authorize the candidate migration artifact, including the proposed narrow ADR 0009 exception for the existing local terminal backend. Prove the live old unit and sidecar, the sanitized new Hermes home, ordinary terminal command and private workspace write inside the new `alfredmsg` service cgroup, gate/media ACLs, and same-host UID denials before any filing. Current read-only metadata and unit syntax checks do **not** prove Personal Alfred will work under a new UID. Keep the old local-terminal configuration intact until the new service passes those checks; roll back on failure.
