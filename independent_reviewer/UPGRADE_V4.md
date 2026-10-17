# Independent Reviewer V1: V3 to V4 host upgrade

This is a future administrator-authorized upgrade procedure. It has not been
run. It replaces only the root-owned Reviewer package after a root-owned trust
handoff. It leaves the Developer, QA, Gateway, CTO plan, grant, Git source,
existing V3 BLOCKED report, and running services untouched. Do not execute a
new T-0002 review without separate authorization.

V4 release manifest SHA-256:

```text
f6f789de9a8bb5e4e6b9dd67db9decc5e8ee760c203ebba6a45ef61532cc5832
```

The installed V3 manifest digest was:

```text
a8eceb9b7a72bb2b601a28cde0cfe7c33e6cd65fb6cee8694abe6d0f1bf8c0d8
```

## 1. Read-only checks

Run as an administrator. Record the existing BLOCKED report digest for audit.
The report and existing Reviewer state must remain in place during the upgrade.

```sh
sudo /usr/bin/sha256sum /opt/alfred-reviewer-v1/independent_reviewer/release.sha256
sudo /bin/sh -c 'cd /opt/alfred-reviewer-v1/independent_reviewer && /usr/bin/sha256sum -c release.sha256'
sudo /usr/bin/sha256sum /opt/alfred-reviewer-v1/bin/codex
sudo /usr/bin/sha256sum /var/lib/alfred-reviewer-state/dev-v1-accept/T-0002/review-report.json
sudo /usr/bin/sha256sum /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/qa-report.json
```

Require V3 manifest `a8eceb9b7a72bb2b601a28cde0cfe7c33e6cd65fb6cee8694abe6d0f1bf8c0d8`,
CLI binary `628e35487d888a28f0427fc37501da529dd3d81fcbad7a2c3421c1e8670d92e1`,
and QA report `c4e71ed4b4f24792d6354b3c7ebc46689869811ca4aca2c7c8217dcffa4817ea`.

## 2. Root-owned V4 preparation

The V4 candidate is user writable. Copy only the pinned file inventory into a
new root-owned location using the system `install` utility, then verify every
byte before executing prepared Python as root. Do not overwrite V3 preparation.

```sh
cd /home/alfred/alfred-development-lab/milestone2/task-a/independent_reviewer/host-candidate-v4/independent_reviewer
/usr/bin/sha256sum release.sha256
/usr/bin/sha256sum -c release.sha256
cd /tmp
sudo /usr/bin/test ! -e /var/lib/alfred-reviewer-prepared-v4
sudo /usr/bin/test ! -L /var/lib/alfred-reviewer-prepared-v4
sudo /usr/bin/install -d -o root -g root -m 0700 /var/lib/alfred-reviewer-prepared-v4/independent_reviewer/schemas
sudo /usr/bin/install -o root -g root -m 0444 -t /var/lib/alfred-reviewer-prepared-v4/independent_reviewer /home/alfred/alfred-development-lab/milestone2/task-a/independent_reviewer/host-candidate-v4/independent_reviewer/{__init__.py,worker.py,host_release.py,config.json,README.md,release.sha256}
sudo /usr/bin/install -o root -g root -m 0444 -t /var/lib/alfred-reviewer-prepared-v4/independent_reviewer/schemas /home/alfred/alfred-development-lab/milestone2/task-a/independent_reviewer/host-candidate-v4/independent_reviewer/schemas/{review-report.schema.json,publication-handoff.schema.json,correction-request.schema.json,model-output.schema.json}
sudo /usr/bin/sha256sum /var/lib/alfred-reviewer-prepared-v4/independent_reviewer/release.sha256
sudo /bin/sh -c 'cd /var/lib/alfred-reviewer-prepared-v4/independent_reviewer && /usr/bin/sha256sum -c release.sha256'
sudo /bin/sh -c 'test -z "$(/usr/bin/find /var/lib/alfred-reviewer-prepared-v4 \( -type l -o ! -user root -o -perm /022 \) -print -quit)"'
sudo /usr/bin/python3 -I -B -c 'import sys; from pathlib import Path; sys.path.insert(0, "/var/lib/alfred-reviewer-prepared-v4"); from independent_reviewer.host_release import verify; print(verify(Path("/var/lib/alfred-reviewer-prepared-v4/independent_reviewer"), "f6f789de9a8bb5e4e6b9dd67db9decc5e8ee760c203ebba6a45ef61532cc5832"))'
```

Both manifest checks must print the V4 digest. Stop if ownership, permissions,
inventory, or hashes differ.

## 3. Controlled package replacement

Choose a unique backup name. Moving the old package preserves exact V3 bytes
and its CLI binary. The old Reviewer output stays at its original path. The
new output root is separate because the worker intentionally returns an
existing report for the same input fingerprint.

```sh
REVIEW_UPGRADE_BACKUP='/var/lib/alfred-reviewer-backups/REPLACE_WITH_UNIQUE_V4_TIMESTAMP'
sudo /usr/bin/test ! -e "$REVIEW_UPGRADE_BACKUP"
sudo /usr/bin/test ! -e /var/lib/alfred-reviewer-state-v4
sudo /usr/bin/install -d -o root -g root -m 0700 "$REVIEW_UPGRADE_BACKUP"
sudo /usr/bin/mv /opt/alfred-reviewer-v1 "$REVIEW_UPGRADE_BACKUP/v3-install"
sudo /usr/bin/install -d -o root -g root -m 0755 /opt/alfred-reviewer-v1/independent_reviewer/schemas /opt/alfred-reviewer-v1/bin
sudo /usr/bin/install -o root -g root -m 0444 -t /opt/alfred-reviewer-v1/independent_reviewer /var/lib/alfred-reviewer-prepared-v4/independent_reviewer/{__init__.py,worker.py,host_release.py,config.json,README.md,release.sha256}
sudo /usr/bin/install -o root -g root -m 0444 -t /opt/alfred-reviewer-v1/independent_reviewer/schemas /var/lib/alfred-reviewer-prepared-v4/independent_reviewer/schemas/{review-report.schema.json,publication-handoff.schema.json,correction-request.schema.json,model-output.schema.json}
sudo /usr/bin/install -o root -g root -m 0555 "$REVIEW_UPGRADE_BACKUP/v3-install/bin/codex" /opt/alfred-reviewer-v1/bin/codex
sudo /usr/bin/sha256sum /opt/alfred-reviewer-v1/bin/codex
sudo /bin/sh -c 'cd /opt/alfred-reviewer-v1/independent_reviewer && /usr/bin/sha256sum -c release.sha256'
sudo /bin/sh -c 'test -z "$(/usr/bin/find /opt/alfred-reviewer-v1 \( -type l -o ! -user root -o -perm /022 \) -print -quit)"'
sudo /usr/bin/python3 -I -B -c 'import sys; from pathlib import Path; sys.path.insert(0, "/opt/alfred-reviewer-v1"); from independent_reviewer.host_release import verify; print(verify(Path("/opt/alfred-reviewer-v1/independent_reviewer"), "f6f789de9a8bb5e4e6b9dd67db9decc5e8ee760c203ebba6a45ef61532cc5832"))'
sudo /usr/bin/install -d -o alfredreview -g alfredreview -m 0700 /var/lib/alfred-reviewer-state-v4
sudo /usr/bin/sha256sum /var/lib/alfred-reviewer-state/dev-v1-accept/T-0002/review-report.json
```

The final report digest must match the recorded pre-upgrade digest. Do not
execute Reviewer after these commands as part of this upgrade. A later,
separately authorized retry must use `--output-root
/var/lib/alfred-reviewer-state-v4` so the V3 BLOCKED report remains intact.

## 4. Exact rollback

Use the same backup path. Preserve the V4 package and any new output for
forensic review. Restore the untouched V3 package without changing existing
Reviewer output, QA evidence, source, grants, or services.

```sh
REVIEW_UPGRADE_BACKUP='/var/lib/alfred-reviewer-backups/REPLACE_WITH_UNIQUE_V4_TIMESTAMP'
sudo /usr/bin/mv /opt/alfred-reviewer-v1 "$REVIEW_UPGRADE_BACKUP/unaccepted-v4-install"
sudo /usr/bin/mv "$REVIEW_UPGRADE_BACKUP/v3-install" /opt/alfred-reviewer-v1
sudo /usr/bin/mv /var/lib/alfred-reviewer-state-v4 "$REVIEW_UPGRADE_BACKUP/v4-output"
sudo /usr/bin/mv /var/lib/alfred-reviewer-prepared-v4 "$REVIEW_UPGRADE_BACKUP/v4-prepared"
sudo /bin/sh -c 'cd /opt/alfred-reviewer-v1/independent_reviewer && /usr/bin/sha256sum -c release.sha256'
```

If a partial step left one path absent, inspect the filesystem and move only
paths that exist; do not overwrite the preserved V3 package or BLOCKED report.
