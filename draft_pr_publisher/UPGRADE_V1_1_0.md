# Publisher V1.1.0: exact source ownership correction

This upgrades an existing, verified Publisher V1 installation. Run from
`/home/alfred/alfred-development-lab/milestone2/task-a` only after operator
approval to install. These commands have not been run on production.
Keep on-demand Publisher invocations paused during installation or rollback.
No service restart is required.

Only `worker.py` and `release.sha256` change in the installed package. The
correction gives the local fetch subprocess a private, temporary Git config
with one `safe.directory`: the canonical approved source path. Its local
upload-pack child inherits that config. Init and push retain `/dev/null` as
their global config, and system config remains disabled. The config disappears
with the temporary repository. No host Git config or source permissions change.

Pinned release:

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-draft-pr-publisher-v1.1.0.tar.gz` | `bacefa3958db55d6bb5b4591e71902aeae55ba8002ffdebb72015dfa309b1052` |
| New `release.sha256` | `926c925fedcaad40ef9240c2558ff9d10f241329f290a99e212a449f1c66442e` |
| New `worker.py` | `051ed86f1fe07260fd663636b665bbef5ddab6c2b8852ecc0a777264ee944ec3` |
| Original V1 `release.sha256` | `53f5a14a58ccaa5d8b9b85242f913a34866a19f31ee7de36f068c682a012fcda` |
| Original V1 `worker.py` | `88eace873994d080000ed0ef12d25107e63223b3fbcf1253e22450e25fde7f76` |

The archive contains exactly the eight runtime files listed by the manifest,
plus `release.sha256`. All seven runtime files other than `worker.py` retain
their original V1 hashes. The archive excludes tests, host procedures, tokens,
authorization records, and publication evidence.

## Prepare the protected handoff

Verify the literal pins before copying. The installation block rechecks the
copies inside the root-owned handoff; it never executes staging Python as root.
Abort if the handoff or backup path already exists and review its contents.

```sh
(
set -eu
printf '%s  %s\n' 'bacefa3958db55d6bb5b4591e71902aeae55ba8002ffdebb72015dfa309b1052' 'dist/alfred-draft-pr-publisher-v1.1.0.tar.gz' | sha256sum -c -
printf '%s  %s\n' '926c925fedcaad40ef9240c2558ff9d10f241329f290a99e212a449f1c66442e' 'draft_pr_publisher/release.sha256' | sha256sum -c -
(cd draft_pr_publisher && sha256sum -c release.sha256)
sudo /usr/bin/test ! -e /root/alfred-publisher-v1.1.0-handoff
sudo /usr/bin/install -d -o root -g root -m 0700 /root/alfred-publisher-v1.1.0-handoff
sudo /usr/bin/install -o root -g root -m 0644 draft_pr_publisher/worker.py draft_pr_publisher/release.sha256 /root/alfred-publisher-v1.1.0-handoff/
)
```

## Install the two files

Run this entire block as one command. It verifies the installed V1 inventory,
saves both original files, stages replacements on the destination filesystem,
then replaces and verifies them. Any ordinary failure after the first
replacement restores and verifies both original files. A failed restoration
prints an explicit error and retains the backup for manual rollback. A power
loss or SIGKILL requires the rollback block below before further invocation.

```bash
sudo /bin/bash <<'INSTALL_PUBLISHER_V1_1_0'
set -Eeuo pipefail
test "$(id -u)" = 0
live=/opt/alfred-draft-pr-publisher-v1
stage=/root/alfred-publisher-v1.1.0-handoff
backup=/root/alfred-publisher-v1.0-rollback
old_manifest=53f5a14a58ccaa5d8b9b85242f913a34866a19f31ee7de36f068c682a012fcda
new_manifest=926c925fedcaad40ef9240c2558ff9d10f241329f290a99e212a449f1c66442e
check_release() {
    printf '%s  %s\n' "$2" "$1/release.sha256" | /usr/bin/sha256sum -c - || return 1
    (cd "$1" && /usr/bin/sha256sum -c release.sha256)
}
test -d "$live" && test ! -L "$live"
test -d "$stage" && test ! -L "$stage"
check_release "$live" "$old_manifest"
printf '%s  %s\n' "$new_manifest" "$stage/release.sha256" '051ed86f1fe07260fd663636b665bbef5ddab6c2b8852ecc0a777264ee944ec3' "$stage/worker.py" | /usr/bin/sha256sum -c -
test ! -e "$backup"
/usr/bin/install -d -o root -g root -m 0700 "$backup"
/bin/cp -p -- "$live/worker.py" "$live/release.sha256" "$backup/"
printf '%s  %s\n' "$old_manifest" "$backup/release.sha256" '88eace873994d080000ed0ef12d25107e63223b3fbcf1253e22450e25fde7f76' "$backup/worker.py" | /usr/bin/sha256sum -c -
armed=0
complete=0
finish() {
    rc=$?
    trap - EXIT
    if test "$armed" = 1 && test "$complete" = 0; then
        if ! (
            set -e
            /bin/cp -p -- "$backup/worker.py" "$live/.worker.v1.0-restore" || exit 1
            /bin/cp -p -- "$backup/release.sha256" "$live/.release.v1.0-restore" || exit 1
            /bin/mv -f -- "$live/.worker.v1.0-restore" "$live/worker.py" || exit 1
            /bin/mv -f -- "$live/.release.v1.0-restore" "$live/release.sha256" || exit 1
            check_release "$live" "$old_manifest"
        ); then
            printf '%s\n' 'RESTORATION FAILED: keep Publisher paused; run the reviewed rollback block.' >&2
            exit 1
        fi
        printf '%s\n' 'Installation failed; original Publisher V1 restored.' >&2
    fi
    exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP
/usr/bin/install -o root -g root -m 0644 "$stage/worker.py" "$live/.worker.v1.1.0"
/usr/bin/install -o root -g root -m 0644 "$stage/release.sha256" "$live/.release.v1.1.0"
armed=1
/bin/mv -f -- "$live/.worker.v1.1.0" "$live/worker.py"
/bin/mv -f -- "$live/.release.v1.1.0" "$live/release.sha256"
check_release "$live" "$new_manifest"
complete=1
INSTALL_PUBLISHER_V1_1_0
```

## Roll back the code correction

This restores the two saved V1 release files and verifies the original complete
inventory. It is also valid after interrupted installation. Keep the backup.
If verification fails, keep Publisher paused and investigate the named file.

```bash
sudo /bin/bash <<'ROLLBACK_PUBLISHER_V1_1_0'
set -Eeuo pipefail
test "$(id -u)" = 0
live=/opt/alfred-draft-pr-publisher-v1
backup=/root/alfred-publisher-v1.0-rollback
test -d "$live" && test ! -L "$live"
test -d "$backup" && test ! -L "$backup"
printf '%s  %s\n' '53f5a14a58ccaa5d8b9b85242f913a34866a19f31ee7de36f068c682a012fcda' "$backup/release.sha256" '88eace873994d080000ed0ef12d25107e63223b3fbcf1253e22450e25fde7f76' "$backup/worker.py" | /usr/bin/sha256sum -c -
/bin/cp -p -- "$backup/worker.py" "$live/.worker.v1.0-restore"
/bin/cp -p -- "$backup/release.sha256" "$live/.release.v1.0-restore"
/bin/mv -f -- "$live/.worker.v1.0-restore" "$live/worker.py"
/bin/mv -f -- "$live/.release.v1.0-restore" "$live/release.sha256"
(cd "$live" && /usr/bin/sha256sum -c release.sha256)
ROLLBACK_PUBLISHER_V1_1_0
```

Installation and rollback preserve the existing publication ERROR result,
publication plan, separate owner authorization, Developer grants, Reviewer and
QA evidence, protected source repository, and Git credentials. Neither block
reads or writes those paths. Do not use the original first-install or token
removal instructions in `HOST_OPERATOR.md` for this correction.

Installation does not authorize another publication attempt. A later operator
action must separately review the retained authorization and any validity
window before invoking Publisher. Do not regenerate the plan or overwrite the
original ERROR result as an installation check.
