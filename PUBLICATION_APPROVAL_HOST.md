# Publication approval: reviewed host installation candidate

Staging only. Nothing in this procedure has been run on the host. It changes the
existing Development Intake code and its release package only. It does not add a
Photon connection, Gateway, service, credential, authorization record, or
GitHub action. Do not use the original `host_install` on an active installation.

The staged release manifest SHA-256 is
`32f6b3c717b044a9e516314984dea314c9d448b4d1c59b9bc1407932e269f568`.
The staged Intake source SHA-256 is
`01c8911332d2314ccbe8db187a4a6d3ba63ceb9d2475c2ad252af7c9a1855ef0`.
The currently installed release manifest is expected to be
`586f92ef61d6cc328c4c5202e5d86dd0d3e47bfa3e42a1e1e08750fef721576c`.
The currently installed Intake source is expected to be
`cef079f4041aea439a3bb58f4ea728e9dd38ae45b4258a1183c962670b0c4a6f`.
Stop if either installed hash differs. The exact publication plan hash is
`511fa533fd9dc5bb41d51bff1baa21b28a54b8b0b670e5b3f0f602a78d38b903`.

## Installation after operator review

Run the staging tests first. The prechecks are read only:

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
echo '32f6b3c717b044a9e516314984dea314c9d448b4d1c59b9bc1407932e269f568  developer_v1/release.sha256' | sha256sum -c -
sha256sum -c developer_v1/release.sha256
echo '586f92ef61d6cc328c4c5202e5d86dd0d3e47bfa3e42a1e1e08750fef721576c  /opt/alfred-developer-v1/developer_v1/release.sha256' | sudo sha256sum -c -
echo 'cef079f4041aea439a3bb58f4ea728e9dd38ae45b4258a1183c962670b0c4a6f  /usr/local/lib/alfred-v1.1/trusted_intake.py' | sudo sha256sum -c -
echo '511fa533fd9dc5bb41d51bff1baa21b28a54b8b0b670e5b3f0f602a78d38b903  /var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-plan.json' | sudo sha256sum -c -
sudo test ! -e /var/lib/alfred-draft-pr-authorizations/T-0002.json
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl show -p ActiveState -p Result alfred-development-gateway.service alfred-development-gateway.timer
```

Back up the installed package and Intake source to a new root-owned mode
`0700` directory. Move the development activation marker into the backup while
replacing code. Only these seven package files change or are added:

- `owner_grants.py`
- `trusted_intake_development.py`
- `publication_approval.py`
- `stage_publication.py`
- `host_install.py`
- `install_config.py`
- `release.sha256`

The reviewed [operator transaction](publication_host_transaction.sh) has
SHA-256 `1a8d001d207ba01515c325829d6143c91fa6478b89267441871cadf63b4f1a6a`.
It is outside the Developer release and adds no service. It checks the pinned
old and new releases, Intake source, exact publication plan, absent
authorization file, activation marker, and service health. It takes a private
backup and copies the seven changed files into a root-owned staging directory,
then verifies those copies **before** moving the activation marker. It
restarts only `alfred-development-intake.service`.

Run this exact installation command only after the separate host installation
authorization. Nothing here has been executed against production:

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
echo '1a8d001d207ba01515c325829d6143c91fa6478b89267441871cadf63b4f1a6a  publication_host_transaction.sh' | sha256sum -c -
sudo /bin/bash /home/alfred/alfred-development-lab/milestone2/task-a/publication_host_transaction.sh install
```

A failed installation exits nonzero. If the activation marker has moved, the
script restores the pinned prior Developer package and Intake source, verifies
them, restarts Intake, and restores the marker. It reports `ROLLED_BACK` on
success. If recovery cannot finish, it reports `BLOCKED` and names both marker
locations; the marker stays in the protected backup until a successful manual
rollback. An uncatchable kill or host power loss also requires the manual
rollback below. Never treat a missing marker as a successful installation.

The exact manual rollback command is:

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
echo '1a8d001d207ba01515c325829d6143c91fa6478b89267441871cadf63b4f1a6a  publication_host_transaction.sh' | sha256sum -c -
sudo /bin/bash /home/alfred/alfred-development-lab/milestone2/task-a/publication_host_transaction.sh rollback
```

Rollback verifies the backup against the pinned prior release, restores only
`/opt/alfred-developer-v1/developer_v1` and
`/usr/local/lib/alfred-v1.1/trusted_intake.py`, restarts only Intake, checks
service and Gateway state, and restores the existing activation marker. It
does not read or alter Developer grant records, QA evidence, Reviewer approval,
the publication plan, or the Publisher authorization directory. A failed
rollback exits nonzero with `BLOCKED`; rerun it after resolving the failed
service or filesystem condition. The disposable fixture test covers a complete
install/rollback, partial install failure, and failed-recovery retry.

The installation command never invokes `stage_publication --stage` or
`--prepare`. The publication challenge and authorization writer require later,
separate root-only commands; no owner reply or authorization record is created
by installing the code.

## Later owner approval, separate from installation

Only after the installation is reviewed and authorized, an administrator may
run the root-only `developer_v1.stage_publication --stage` client against the
existing Intake socket with the verified owner DM ID. It reads only
`/var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-plan.json`,
checks its exact digest and fields, and sends one publication challenge over the
existing Photon connection. A fresh authenticated owner reply must target that
message directly within five minutes and match the printed phrase exactly.
The `--prepare --reference <challenge>` operation is available only after
Intake has recorded and rechecked the owner decision and issuance digests. It
writes the Publisher schema record once to
`/var/lib/alfred-draft-pr-authorizations/T-0002.json`, root-owned, group
`alfredpublish`, mode `0640`; its existing parent must be root-owned and not
writable by group or others. The client never accepts a caller supplied
`owner_event_id`. No authorization is created by this staging work.

The future administrator commands, after the parent directory is verified
root-owned, group `alfredpublish`, mode `0750`, are:

```bash
sudo env PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.stage_publication --socket /run/alfred-development-intake/intake.sock --stage --space-id '<VERIFIED_OWNER_DM_SPACE_ID>'
# Wait for a fresh authenticated native reply to that message.
sudo env PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.stage_publication --socket /run/alfred-development-intake/intake.sock --prepare --reference '<CHALLENGE_REFERENCE>'
```
