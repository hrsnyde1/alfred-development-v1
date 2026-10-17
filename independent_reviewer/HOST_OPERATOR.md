# Independent Reviewer V1 host procedure

This is a future administrator-authorized, on-demand installation and T-0002
acceptance procedure. It has **not** been run. It does not restart services,
alter Developer or QA output, or contact GitHub. Stop if any command fails.

Reviewer package manifest SHA-256:

```text
a8eceb9b7a72bb2b601a28cde0cfe7c33e6cd65fb6cee8694abe6d0f1bf8c0d8
```

Pinned Codex CLI binary SHA-256 (standalone 0.162.1):

```text
628e35487d888a28f0427fc37501da529dd3d81fcbad7a2c3421c1e8670d92e1
```

## 1. Read-only inspection

The first two files are private to `alfredqa`. Run these read-only commands as
an administrator and inspect the actual JSON. The QA report hash must equal the
trusted host acceptance value below, and the handoff's `qa_report_sha256` must
match it. The decision in both files must be `PASS`.

```sh
sudo /usr/bin/sha256sum /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/qa-report.json
sudo /usr/bin/cat /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/reviewer-handoff.json
sudo /usr/bin/cat /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/qa-report.json
/usr/bin/git -C /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final rev-parse HEAD
/usr/bin/sha256sum /home/alfred/.codex/packages/standalone/releases/0.162.1-x86_64-unknown-linux-musl/bin/codex
```

Expected QA report SHA-256:

```text
c4e71ed4b4f24792d6354b3c7ebc46689869811ca4aca2c7c8217dcffa4817ea
```

Expected final revision:

```text
89ba188f8a2f801d433a30c9c21363efb3e1043d
```

## 2. Root-owned release preparation

The source release is user writable. Copy exactly its listed files with the
system `install` utility before executing any of its Python as root. These
commands require administrator authorization. Verify the root-owned copy
against the pinned digest. Preserve prior QA releases and backups.

```sh
cd /home/alfred/alfred-development-lab/milestone2/task-a/independent_reviewer/host-candidate-v3/independent_reviewer
/usr/bin/sha256sum release.sha256
/usr/bin/sha256sum -c release.sha256
cd /tmp
sudo /usr/bin/test ! -e /var/lib/alfred-reviewer-prepared-v3
sudo /usr/bin/test ! -L /var/lib/alfred-reviewer-prepared-v3
sudo /usr/bin/install -d -o root -g root -m 0700 /var/lib/alfred-reviewer-prepared-v3/independent_reviewer/schemas
sudo /usr/bin/install -o root -g root -m 0444 -t /var/lib/alfred-reviewer-prepared-v3/independent_reviewer /home/alfred/alfred-development-lab/milestone2/task-a/independent_reviewer/host-candidate-v3/independent_reviewer/{__init__.py,worker.py,host_release.py,config.json,README.md,release.sha256}
sudo /usr/bin/install -o root -g root -m 0444 -t /var/lib/alfred-reviewer-prepared-v3/independent_reviewer/schemas /home/alfred/alfred-development-lab/milestone2/task-a/independent_reviewer/host-candidate-v3/independent_reviewer/schemas/{review-report.schema.json,publication-handoff.schema.json,correction-request.schema.json,model-output.schema.json}
sudo /usr/bin/sha256sum /var/lib/alfred-reviewer-prepared-v3/independent_reviewer/release.sha256
sudo /bin/sh -c 'cd /var/lib/alfred-reviewer-prepared-v3/independent_reviewer && /usr/bin/sha256sum -c release.sha256'
sudo /bin/sh -c 'test -z "$(/usr/bin/find /var/lib/alfred-reviewer-prepared-v3 \( -type l -o ! -user root -o -perm /022 \) -print -quit)"'
sudo /usr/bin/python3 -I -B -c 'import sys; from pathlib import Path; sys.path.insert(0, "/var/lib/alfred-reviewer-prepared-v3"); from independent_reviewer.host_release import verify; print(verify(Path("/var/lib/alfred-reviewer-prepared-v3/independent_reviewer"), "a8eceb9b7a72bb2b601a28cde0cfe7c33e6cd65fb6cee8694abe6d0f1bf8c0d8"))'
```

Both manifest checks must print the pinned digest. The isolated verifier also
rejects extra files, missing files, symlinks and changed bytes. Root-owned
preparation is the trust handoff; no Python from the user-writable release is
executed as root.

## 3. Controlled host installation

Create a dedicated `alfredreview` identity only if absent. It gets no grant,
Gateway, Developer, or QA authority. Copy the verified package and the pinned
CLI binary to `/opt`. Provision its own Codex login interactively later; do
not copy credentials from Developer or QA identities.

```sh
sudo /usr/bin/test ! -e /opt/alfred-reviewer-v1
sudo /usr/bin/test ! -L /opt/alfred-reviewer-v1
sudo /usr/bin/test ! -e /var/lib/alfred-reviewer-evidence
sudo /usr/bin/test ! -L /var/lib/alfred-reviewer-evidence
sudo /usr/bin/test ! -e /var/lib/alfred-reviewer-snapshot
sudo /usr/bin/test ! -L /var/lib/alfred-reviewer-snapshot
sudo /usr/bin/test ! -e /var/lib/alfred-reviewer-state
sudo /usr/bin/test ! -L /var/lib/alfred-reviewer-state
sudo /usr/sbin/useradd --system --home-dir /var/lib/alfred-reviewer-home --create-home --shell /usr/sbin/nologin alfredreview
sudo /usr/bin/chmod 0700 /var/lib/alfred-reviewer-home
sudo /usr/bin/install -d -o root -g root -m 0755 /opt/alfred-reviewer-v1/independent_reviewer/schemas /opt/alfred-reviewer-v1/bin
sudo /usr/bin/install -o root -g root -m 0444 -t /opt/alfred-reviewer-v1/independent_reviewer /var/lib/alfred-reviewer-prepared-v3/independent_reviewer/{__init__.py,worker.py,host_release.py,config.json,README.md,release.sha256}
sudo /usr/bin/install -o root -g root -m 0444 -t /opt/alfred-reviewer-v1/independent_reviewer/schemas /var/lib/alfred-reviewer-prepared-v3/independent_reviewer/schemas/{review-report.schema.json,publication-handoff.schema.json,correction-request.schema.json,model-output.schema.json}
sudo /usr/bin/install -o root -g root -m 0555 /home/alfred/.codex/packages/standalone/releases/0.162.1-x86_64-unknown-linux-musl/bin/codex /opt/alfred-reviewer-v1/bin/codex
sudo /usr/bin/sha256sum /opt/alfred-reviewer-v1/bin/codex
sudo /bin/sh -c 'cd /opt/alfred-reviewer-v1/independent_reviewer && /usr/bin/sha256sum -c release.sha256'
sudo /bin/sh -c 'test -z "$(/usr/bin/find /opt/alfred-reviewer-v1 \( -type l -o ! -user root -o -perm /022 \) -print -quit)"'
sudo /usr/bin/python3 -I -B -c 'import sys; from pathlib import Path; sys.path.insert(0, "/opt/alfred-reviewer-v1"); from independent_reviewer.host_release import verify; print(verify(Path("/opt/alfred-reviewer-v1/independent_reviewer"), "a8eceb9b7a72bb2b601a28cde0cfe7c33e6cd65fb6cee8694abe6d0f1bf8c0d8"))'
```

The CLI hash must equal the pinned value above. Install the reviewed QA
evidence as a separate root-owned, exact-copy handoff. This grants Reviewer
read access only to five required copies, not the original QA state, Gateway,
or grant directory.

```sh
sudo /usr/bin/install -d -o root -g root -m 0700 /var/lib/alfred-reviewer-evidence
sudo /usr/bin/install -d -o root -g root -m 0700 /var/lib/alfred-reviewer-evidence/T-0002
sudo /usr/bin/install -o root -g root -m 0600 /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/qa-report.json /var/lib/alfred-reviewer-evidence/T-0002/qa-report.json
sudo /usr/bin/install -o root -g root -m 0600 /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/reviewer-handoff.json /var/lib/alfred-reviewer-evidence/T-0002/reviewer-handoff.json
sudo /usr/bin/install -o root -g root -m 0600 /var/lib/alfred-independent-qa-evidence/gateway/cto-plans/dev-v1-accept-T-0002.json /var/lib/alfred-reviewer-evidence/T-0002/cto-plan.json
sudo /usr/bin/install -o root -g root -m 0600 /var/lib/alfred-independent-qa-evidence/grants/grant-445759a699d9423bbb5a8f1dd589689a.json /var/lib/alfred-reviewer-evidence/T-0002/grant.json
sudo /usr/bin/install -o root -g root -m 0600 /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo/.dev/tasks/T-0002-backend-calculator-subtract-helper.md /var/lib/alfred-reviewer-evidence/T-0002/task-spec.md
sudo /usr/bin/setfacl -m u:alfredreview:r-x /var/lib/alfred-reviewer-evidence /var/lib/alfred-reviewer-evidence/T-0002
sudo /usr/bin/setfacl -m u:alfredreview:r-- /var/lib/alfred-reviewer-evidence/T-0002/{qa-report.json,reviewer-handoff.json,cto-plan.json,grant.json,task-spec.md}
sudo /usr/bin/sha256sum /var/lib/alfred-reviewer-evidence/T-0002/qa-report.json
```

The copied QA report must still hash to
`c4e71ed4b4f24792d6354b3c7ebc46689869811ca4aca2c7c8217dcffa4817ea`.
The worker compares all other copies against digests inside that pinned report.

Create an independent Git clone from the final worktree. This makes the
Reviewer inspect exact Git objects without ACL access to Developer worktrees.
It is a dedicated snapshot, not a shared object store.

```sh
sudo /usr/bin/install -d -o root -g root -m 0700 /var/lib/alfred-reviewer-snapshot
sudo /usr/bin/git -c safe.directory=/var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final clone --no-local --no-checkout /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final /var/lib/alfred-reviewer-snapshot
sudo /usr/bin/git -C /var/lib/alfred-reviewer-snapshot checkout --detach 89ba188f8a2f801d433a30c9c21363efb3e1043d
sudo /usr/bin/chown -R root:root /var/lib/alfred-reviewer-snapshot
sudo /usr/bin/find /var/lib/alfred-reviewer-snapshot -type d -exec /usr/bin/chmod 0700 {} +
sudo /usr/bin/find /var/lib/alfred-reviewer-snapshot -type f -exec /usr/bin/chmod 0600 {} +
sudo /usr/bin/find /var/lib/alfred-reviewer-snapshot -type d -exec /usr/bin/setfacl -m u:alfredreview:r-x {} +
sudo /usr/bin/find /var/lib/alfred-reviewer-snapshot -type f -exec /usr/bin/setfacl -m u:alfredreview:r-- {} +
sudo /bin/sh -c 'test -z "$(/usr/bin/find /var/lib/alfred-reviewer-snapshot -type l -print -quit)"'
sudo /usr/bin/install -d -o alfredreview -g alfredreview -m 0700 /var/lib/alfred-reviewer-state
```

The Reviewer account needs its own authenticated model session. The following
command is interactive and requires administrator authorization and owner
control of the login. Run it only after the package and identity are checked.

```sh
sudo /usr/sbin/runuser -u alfredreview -- /opt/alfred-reviewer-v1/bin/codex login --device-auth
sudo /usr/sbin/runuser -u alfredreview -- /opt/alfred-reviewer-v1/bin/codex login status
```

## 4. Actual permission and integrity preflight

These probes use the real Reviewer UID. `test -w` must fail for source and QA
evidence. There is no ACL or group grant on the original Developer, QA,
Gateway, or grant directories.

```sh
sudo /usr/sbin/runuser -u alfredreview -- /usr/bin/test -r /var/lib/alfred-reviewer-evidence/T-0002/qa-report.json
sudo /usr/sbin/runuser -u alfredreview -- /usr/bin/test -r /var/lib/alfred-reviewer-snapshot/calculator.py
sudo /bin/sh -c '! /usr/sbin/runuser -u alfredreview -- /usr/bin/test -w /var/lib/alfred-reviewer-evidence/T-0002/qa-report.json'
sudo /bin/sh -c '! /usr/sbin/runuser -u alfredreview -- /usr/bin/test -w /var/lib/alfred-reviewer-snapshot/calculator.py'
sudo /bin/sh -c '! /usr/sbin/runuser -u alfredreview -- /usr/bin/test -r /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/qa-report.json'
sudo /bin/sh -c '! /usr/sbin/runuser -u alfredreview -- /usr/bin/test -r /var/lib/alfred-development-grants/grant-445759a699d9423bbb5a8f1dd589689a.json'
sudo /bin/sh -c '! /usr/sbin/runuser -u alfredreview -- /usr/bin/test -w /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0002.json'
sudo /usr/sbin/runuser -u alfredreview -- /usr/bin/test -w /var/lib/alfred-reviewer-state
sudo /usr/bin/git -C /var/lib/alfred-reviewer-snapshot rev-parse HEAD
```

Also check the original Developer worktrees, QA report digest and Gateway/grant
hashes against the values recorded before installation. Stop if any changed.

## 5. Controlled live T-0002 Reviewer acceptance — separate authorization

Run only after steps 1–4 pass and live review is separately authorized. This
does not publish. A successful result writes `review-report.json` and a
`publication-handoff.json` under `/var/lib/alfred-reviewer-state`.

```sh
sudo /usr/sbin/runuser -u alfredreview -- /usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0, "/opt/alfred-reviewer-v1"); from independent_reviewer.worker import main; main()' --handoff /var/lib/alfred-reviewer-evidence/T-0002/reviewer-handoff.json --qa-report /var/lib/alfred-reviewer-evidence/T-0002/qa-report.json --final-worktree /var/lib/alfred-reviewer-snapshot --cto-plan /var/lib/alfred-reviewer-evidence/T-0002/cto-plan.json --grant /var/lib/alfred-reviewer-evidence/T-0002/grant.json --task-spec /var/lib/alfred-reviewer-evidence/T-0002/task-spec.md --config /opt/alfred-reviewer-v1/independent_reviewer/config.json --output-root /var/lib/alfred-reviewer-state
sudo /usr/bin/sha256sum /var/lib/alfred-reviewer-state/dev-v1-accept/T-0002/review-report.json
sudo /usr/bin/cat /var/lib/alfred-reviewer-state/dev-v1-accept/T-0002/review-report.json
sudo /usr/bin/cat /var/lib/alfred-reviewer-state/dev-v1-accept/T-0002/publication-handoff.json
```

Require APPROVED, exact final revision, the expected QA report digest,
`calculator.py` as the sole changed file, its verified SHA-256, model identity
`codex/gpt-6-astra`, and a publication handoff whose review report digest
matches the new report. If the result requests changes or is blocked, no
publication handoff may exist. Publication remains a separate authorized stage.

## 6. Exact rollback

Preserve all Reviewer evidence in a new root-private backup. No protected ACL
was changed, so rollback requires no Developer or QA ACL restoration. Substitute
a unique reviewed timestamp before running these administrator commands.

```sh
REVIEW_BACKUP='/var/lib/alfred-reviewer-backups/REPLACE_WITH_UNIQUE_TIMESTAMP'
sudo /usr/bin/install -d -o root -g root -m 0700 "$REVIEW_BACKUP"
sudo /usr/bin/mv /opt/alfred-reviewer-v1 "$REVIEW_BACKUP/package"
sudo /usr/bin/mv /var/lib/alfred-reviewer-evidence "$REVIEW_BACKUP/evidence"
sudo /usr/bin/mv /var/lib/alfred-reviewer-snapshot "$REVIEW_BACKUP/snapshot"
sudo /usr/bin/mv /var/lib/alfred-reviewer-state "$REVIEW_BACKUP/output"
sudo /usr/bin/mv /var/lib/alfred-reviewer-prepared-v3 "$REVIEW_BACKUP/prepared-release"
```

Keep `alfredreview` and its private authentication home disabled from further
use until credentials and account lifecycle are reviewed; do not delete the
historical evidence or credentials as an automatic rollback side effect.
