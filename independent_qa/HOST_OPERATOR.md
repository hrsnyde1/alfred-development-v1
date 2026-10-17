# Independent QA V1 host operator procedure

This procedure installs only a root-owned, on-demand QA package and a private
QA report directory. It does not install or restart a service. Run it from an
administrator terminal after reviewing the staged release. The commands using
`sudo` require administrator authorization; they have **not** been run in this
session because noninteractive sudo requires a password.

Release manifest SHA-256:

```text
be55fcbe1753ecf87f682dc6af31ef2bb004f8d142a63edae5b7a2612cf41856
```

Release directory:

```text
/home/alfred/alfred-development-lab/milestone2/task-a/independent_qa/host-candidate-v9/independent_qa
```

## 1. Read-only host inspection

```sh
id alfredqa
systemctl status alfred-dev-qa-runner.socket alfred-dev-qa-snapshot.socket alfred-dev-qa-auth.socket --no-pager --lines=0
getfacl -ep /var/lib/alfred-development-state /var/lib/alfred-development-state/dev-v1-accept /var/lib/alfred-development-state/dev-v1-accept/T-0002 /var/lib/alfred-development-state/dev-v1-accept/T-0002/.lock /var/lib/alfred-development-state/dev-v1-accept/T-0002/backend-subtract.json
namei -l /var/lib/alfred-development-state/dev-v1-accept/T-0002/qa-input.json
namei -l /var/lib/alfred-development-grants/grant-445759a699d9423bbb5a8f1dd589689a.json
namei -l /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final/calculator.py
git -C /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo rev-parse HEAD
git -C /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-backend-subtract rev-parse HEAD
git -C /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final rev-parse HEAD
sha256sum /var/lib/alfred-development-state/dev-v1-accept/T-0002/qa-input.json /var/lib/alfred-development-state/dev-v1-accept/T-0002/report-backend-subtract.json /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final/calculator.py
```

Expected hashes: QA input `62b2657cb31747b368c0c066107a4afa42ea21350e82563a9b67ed16964a0171`,
Developer report `81f924168f3452b3507650ce4f58ace315dbff7fb33de14d42b97550e2cdeb6d`,
and `calculator.py` `8b7592a111b9a05664ec660fb67d926fa3810ff816dd5fb50ea37eae72284c5b`.
The canonical repository remains at baseline `9000574c4c8807e84c4350e2fd342deeba341d7d`.

The V8 failure occurred in `stage_evidence()` before the installer applied QA
ACLs to protected Developer and Git paths or created the QA output directory.
Its exception path restores the saved ACLs and moves the partial evidence and
package into a protected backup. The final package, evidence, and output paths
are absent. Backup contents require administrator access to inspect; preserve
both historical failure backups. Inspect them without changing them before a
new installation:

```sh
sudo /usr/bin/find /var/lib/alfred-independent-qa-backups -maxdepth 6 -printf '%M %u:%g %p\n'
sudo /usr/bin/getfacl -ep /var/lib/alfred-development-state /var/lib/alfred-development-state/dev-v1-accept /var/lib/alfred-development-state/dev-v1-accept/T-0002 /var/lib/alfred-development-state/dev-v1-accept/T-0002/.lock
sudo /usr/bin/ls -ld /opt/alfred-independent-qa-v1 /var/lib/alfred-independent-qa-state /var/lib/alfred-independent-qa-evidence 2>&1
```

Identify the backup created by the V8 attempt. Confirm it contains
`acl-single.txt`, `acl-trees.txt`, `service-access-before.json`,
`unaccepted-package`, and `unaccepted-evidence`. No `unaccepted-output` is
expected for this failure because the output directory is created later.
Confirm the package, evidence, and output destinations above are absent and
the protected ACLs have been restored. Stop for investigation if the backup
inventory or live permissions differ; do not remove or overwrite either
historical backup.

The old prepared releases at `/var/lib/alfred-independent-qa-prepared-v1` and
`/var/lib/alfred-independent-qa-prepared-v2` remain inactive and are not
overwritten. This procedure uses a new prepared path.

## 2. Verify the user-staged release before the trust handoff

```sh
cd /home/alfred/alfred-development-lab/milestone2/task-a/independent_qa/host-candidate-v9/independent_qa
sha256sum release.sha256
sha256sum -c release.sha256
```

The first command must print the pinned hash above; the second must report
`OK` for every listed file. This check is advisory because the source is still
user writable. The authoritative check occurs on the root-owned copy below.

## 3. Root-owned release preparation and authoritative pin check

These **administrator-authorized** commands copy bytes with the system
`install` utility. They execute no Python or shell script from the writable
release. The prepared directory and every copied file must be root owned and
non-user-writable. Stop if any command fails or any hash differs. Do not add
files to this directory.

```sh
cd /tmp
sudo /usr/bin/test ! -e /var/lib/alfred-independent-qa-prepared-v3
sudo /usr/bin/test ! -L /var/lib/alfred-independent-qa-prepared-v3
sudo /usr/bin/install -d -o root -g root -m 0700 /var/lib/alfred-independent-qa-prepared-v3
sudo /usr/bin/install -d -o root -g root -m 0700 /var/lib/alfred-independent-qa-prepared-v3/independent_qa
sudo /usr/bin/install -d -o root -g root -m 0700 /var/lib/alfred-independent-qa-prepared-v3/independent_qa/schemas
sudo /usr/bin/install -o root -g root -m 0444 -t /var/lib/alfred-independent-qa-prepared-v3/independent_qa /home/alfred/alfred-development-lab/milestone2/task-a/independent_qa/host-candidate-v9/independent_qa/{__init__.py,worker.py,config.json,host_preflight.py,host_release.py,host_install.py,host_acceptance.py,README.md,release.sha256}
sudo /usr/bin/install -o root -g root -m 0444 -t /var/lib/alfred-independent-qa-prepared-v3/independent_qa/schemas /home/alfred/alfred-development-lab/milestone2/task-a/independent_qa/host-candidate-v9/independent_qa/schemas/{qa-report.schema.json,reviewer-handoff.schema.json,correction-request.schema.json}
sudo /usr/bin/sha256sum /var/lib/alfred-independent-qa-prepared-v3/independent_qa/release.sha256
sudo /bin/sh -c 'cd /var/lib/alfred-independent-qa-prepared-v3/independent_qa && /usr/bin/sha256sum -c release.sha256'
sudo /bin/sh -c 'test -z "$(/usr/bin/find /var/lib/alfred-independent-qa-prepared-v3 \( -type l -o ! -user root -o -perm /022 \) -print -quit)"'
sudo /usr/bin/python3 -I -B -c 'import sys; from pathlib import Path; sys.path.insert(0, "/var/lib/alfred-independent-qa-prepared-v3"); from independent_qa.host_release import verify; print(verify(Path("/var/lib/alfred-independent-qa-prepared-v3/independent_qa"), "be55fcbe1753ecf87f682dc6af31ef2bb004f8d142a63edae5b7a2612cf41856"))'
```

Both `sha256sum` of the copied manifest and the isolated Python verifier must
print the pinned hash. The verifier also rejects an extra file, missing file,
symlink, or changed executable. Only after those checks may administrator Python
import the prepared package. `-I` ignores the current directory and user
`PYTHONPATH`.

## 4. Controlled installation and actual Linux permission preflight

The installer copies this verified root-owned release into
`/opt/alfred-independent-qa-v1`. It saves original ACLs under a root-private
`/var/lib/alfred-independent-qa-backups/<timestamp>` directory, adds traversal
on the parent directories of the calculator repository and its two T-0002
worktrees, and read-only ACLs on those Git trees. It does not grant `alfredqa`
traversal into the original Developer state, Gateway, registry, or grant
directories. QA reports go only to
`/var/lib/alfred-independent-qa-state`, owned by `alfredqa` with mode `0700`.

The installer also creates `/var/lib/alfred-independent-qa-evidence`, a
root-owned handoff containing only 11 required evidence files: the exact QA
input and Developer report, the task request, registry, CTO plan, and six grant
records. `alfredqa` receives read ACLs on these copies and no write ACL. The
original `.lock` and `backend-subtract.json` remain untouched and inaccessible
to QA. The handoff manifest records each copy's SHA-256; preflight and final
acceptance compare every copy against its canonical source. The QA input and
Developer report must also match their pinned hashes.

The ACL plan explicitly denies `alfredqa` entry to the separate `dev-001`
repository and worktree and the unrelated Alfred projects directory. The
installer saves effective read, write, and traversal results for every ACL
target under each real service UID (`alfredmsg`, `alfredphoton`, `alfreddev`)
before applying ACLs. It re-runs those OS probes afterward and rejects any
change, even if the displayed ACL entries look unchanged.

The installer invokes the standalone permission preflight as the real
`alfredqa` UID before accepting the package. It verifies the copied evidence
and Git objects, attempts `O_WRONLY` opens of QA-readable files without
changing them, rejects read access to the original protected evidence and
other projects, and verifies the dedicated QA output is writable. On failure,
the installer restores ACLs and moves the unaccepted package, output, and
evidence handoff into the protected backup directory.

```sh
cd /tmp
sudo /usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0, "/var/lib/alfred-independent-qa-prepared-v3"); from independent_qa.host_install import main; main()' --release /var/lib/alfred-independent-qa-prepared-v3/independent_qa --manifest-sha256 be55fcbe1753ecf87f682dc6af31ef2bb004f8d142a63edae5b7a2612cf41856
```

Record the returned `backup` path. Run the standalone administrator preflight
again after installation. Substitute the exact returned path for `QA_BACKUP`:

```sh
QA_BACKUP='/var/lib/alfred-independent-qa-backups/REPLACE_WITH_TIMESTAMP_FROM_INSTALL_RESULT'
sudo /usr/bin/env PYTHONPATH=/opt/alfred-independent-qa-v1 /usr/bin/python3 -B -m independent_qa.host_preflight --install-root /opt/alfred-independent-qa-v1 --output-root /var/lib/alfred-independent-qa-state --baseline "$QA_BACKUP/service-access-before.json"
```

Both preflight results must be `PASS`. The existing QA sockets are not changed
or used for this package; their historical runner supports only a fixed
calculator snapshot and does not implement the complete QA handoff contract.

## 5. Controlled live T-0002 QA acceptance (future authorized step)

This executes the installed worker as `alfredqa`. It reads the verified,
root-owned evidence handoff whose bytes match the original `qa-input.json` and
other canonical records. It does **not** copy a staged QA report into production.

```sh
sudo /usr/sbin/runuser -u alfredqa -- /usr/bin/env PYTHONPATH=/opt/alfred-independent-qa-v1 /usr/bin/python3 -B -m independent_qa.worker --qa-input /var/lib/alfred-independent-qa-evidence/dev-v1-accept/T-0002/qa-input.json --output-root /var/lib/alfred-independent-qa-state --registry /var/lib/alfred-independent-qa-evidence/registry/projects.yaml --gateway-state /var/lib/alfred-independent-qa-evidence/gateway --grant-root /var/lib/alfred-independent-qa-evidence/grants --config /opt/alfred-independent-qa-v1/independent_qa/config.json
sudo /usr/bin/env PYTHONPATH=/opt/alfred-independent-qa-v1 /usr/bin/python3 -B -m independent_qa.host_acceptance --install-root /opt/alfred-independent-qa-v1 --output-root /var/lib/alfred-independent-qa-state
```

The acceptance verifier validates both JSON schemas; the project, task, CTO
plan and grant references; Developer commit `867fde90acf3f0055af79bda53a0fccb55f6bf34`;
final revision `89ba188f8a2f801d433a30c9c21363efb3e1043d`; the sole changed
file and hash; both independent checks and the existing two-test unittest
suite; QA PASS; the Reviewer handoff report digest; and unchanged Developer
worktrees and canonical repository. The canonical task spec is the expected
preexisting untracked file in that repository. The acceptance result must be
`PASS`. The Reviewer receives the new production `reviewer-handoff.json` only
after this check passes.

## 6. Exact rollback

Use the `backup` path printed by the installer. Substitute that exact path for
`QA_BACKUP` below. These **administrator-authorized** commands restore the
original ACLs and move the QA package, output, and evidence handoff to the protected backup for
forensic review. They do not touch Developer commits, Gateway, Photon, or
running services.

```sh
QA_BACKUP='/var/lib/alfred-independent-qa-backups/REPLACE_WITH_TIMESTAMP_FROM_INSTALL_RESULT'
sudo /usr/bin/setfacl --restore="$QA_BACKUP/acl-trees.txt"
sudo /usr/bin/setfacl --restore="$QA_BACKUP/acl-single.txt"
sudo /usr/bin/mv /opt/alfred-independent-qa-v1 "$QA_BACKUP/rolled-back-package"
sudo /usr/bin/mv /var/lib/alfred-independent-qa-state "$QA_BACKUP/rolled-back-output"
sudo /usr/bin/mv /var/lib/alfred-independent-qa-evidence "$QA_BACKUP/rolled-back-evidence"
sudo /usr/bin/mv /var/lib/alfred-independent-qa-prepared-v3 "$QA_BACKUP/rolled-back-prepared-release"
```

Confirm no QA service was added and the original socket states remain as
observed in step 1.
