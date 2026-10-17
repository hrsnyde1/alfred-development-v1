# Draft PR Publisher V1: future host operator procedure

For the existing installed Publisher's Git ownership correction, use
[UPGRADE_V1_1_0.md](UPGRADE_V1_1_0.md). This document retains the original V1
first-install pins and is not the V1.1.0 upgrade or rollback procedure.

This document is a procedure, not an authorization. Do not run `publish` until
the owner separately approves a Draft PR for the exact prepared plan. No Alfred
service restart is needed. The publisher runs on demand.

## 1. Read-only host inspection

```sh
sudo /usr/bin/sha256sum /var/lib/alfred-reviewer-state-v4/dev-v1-accept/T-0002/review-report.json
sudo /usr/bin/sha256sum /var/lib/alfred-reviewer-state-v4/dev-v1-accept/T-0002/publication-handoff.json
sudo /usr/bin/sha256sum /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/qa-report.json
sudo /usr/bin/sha256sum /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/reviewer-handoff.json
sudo /usr/bin/git -C /var/lib/alfred-reviewer-snapshot rev-parse HEAD
sudo /usr/bin/git -C /var/lib/alfred-reviewer-snapshot rev-parse 9000574c4c8807e84c4350e2fd342deeba341d7d
sudo /usr/bin/getent passwd alfredpublish
sudo /usr/bin/getent group alfredpublish
```

The first three digests must equal the pinned values in `config.json` (QA:
`c4e71ed4b4f24792d6354b3c7ebc46689869811ca4aca2c7c8217dcffa4817ea`,
Reviewer report:
`f89c6aeba78da509c3fc5c3e336abfba159e544369f44cac4277fc889e6be73d`,
publication handoff:
`0e43ed81cc0a52b91cc7188c07e3c8d48c2ac3b9ba76f83e19e7cda49cd37041`).
The snapshot HEAD must be
`89ba188f8a2f801d433a30c9c21363efb3e1043d`. The canonical registry must
still explicitly map `dev-v1-accept` to
`hrsnyde1/alfred-dev-v1-acceptance` on `main`. Confirm that GitHub repository
exists, that its `main` is the approved baseline, and that the dedicated token
has access before requesting publication authorization. An absent repository or
base branch is a prerequisite, never a reason to select another destination.

## 2. Protected release preparation and installation — administrator action

Run from the reviewed staging workspace. Compare the printed `release.sha256`
digest to the exact value supplied with this release before continuing. The
handoff copies data only; it does not run Python from user-writable staging as
root. Use the literal pinned digest below, not a value computed from writable staging.

```sh
sudo /usr/bin/test ! -e /root/alfred-draft-pr-release-v1
sudo /usr/bin/install -d -o root -g root -m 0700 /root/alfred-draft-pr-release-v1
sudo /usr/bin/install -d -o root -g root -m 0700 /root/alfred-draft-pr-release-v1/schemas
sudo /usr/bin/install -o root -g root -m 0644 draft_pr_publisher/__init__.py draft_pr_publisher/worker.py draft_pr_publisher/config.json draft_pr_publisher/README.md draft_pr_publisher/release.sha256 /root/alfred-draft-pr-release-v1/
sudo /usr/bin/install -o root -g root -m 0755 draft_pr_publisher/askpass.py /root/alfred-draft-pr-release-v1/askpass.py
sudo /usr/bin/install -o root -g root -m 0644 draft_pr_publisher/schemas/publication-plan.schema.json draft_pr_publisher/schemas/owner-authorization.schema.json draft_pr_publisher/schemas/publication-result.schema.json /root/alfred-draft-pr-release-v1/schemas/
printf '%s  %s\n' '53f5a14a58ccaa5d8b9b85242f913a34866a19f31ee7de36f068c682a012fcda' '/root/alfred-draft-pr-release-v1/release.sha256' | sudo /usr/bin/sha256sum -c -
sudo /bin/sh -c 'cd /root/alfred-draft-pr-release-v1 && /usr/bin/sha256sum -c release.sha256'
sudo /usr/bin/test ! -e /opt/alfred-draft-pr-publisher-v1
sudo /usr/bin/install -d -o root -g root -m 0755 /opt/alfred-draft-pr-publisher-v1
sudo /bin/cp -a /root/alfred-draft-pr-release-v1/. /opt/alfred-draft-pr-publisher-v1/
sudo /bin/sh -c 'cd /opt/alfred-draft-pr-publisher-v1 && /usr/bin/sha256sum -c release.sha256'
```

Abort if either `test ! -e` fails; preserve the existing path and review an
upgrade separately. Only the explicitly named files cross into the protected
release. `askpass.py` must retain executable mode 0755.
Do not execute `host` or `worker` Python as root.

Create `alfredpublish` as a separate identity if absent. Its home and state
directory should be its only writable location. Existing Developer, QA,
Reviewer, Gateway, grant, and worktree permissions stay unchanged.

```sh
sudo /usr/sbin/groupadd --system alfredpublish
sudo /usr/sbin/useradd --system --gid alfredpublish --home-dir /var/lib/alfred-draft-pr-state --shell /usr/sbin/nologin alfredpublish
sudo /usr/bin/install -d -o alfredpublish -g alfredpublish -m 0700 /var/lib/alfred-draft-pr-state
sudo /usr/bin/install -d -o root -g alfredpublish -m 0750 /var/lib/alfred-draft-pr-evidence
sudo /usr/bin/install -d -o root -g alfredpublish -m 0750 /var/lib/alfred-draft-pr-evidence/T-0002
sudo /usr/bin/install -d -o root -g alfredpublish -m 0750 /var/lib/alfred-draft-pr-authorizations
sudo /usr/bin/install -d -o root -g alfredpublish -m 0750 /var/lib/alfred-draft-pr-private
```

Copy only the exact evidence needed. The source files are never rewritten.
If the publisher identity or group already exists, skip its corresponding
creation command after verifying it is dedicated to this stage.

```sh
sudo /usr/bin/install -o root -g alfredpublish -m 0640 /var/lib/alfred-reviewer-state-v4/dev-v1-accept/T-0002/review-report.json /var/lib/alfred-draft-pr-evidence/T-0002/review-report.json
sudo /usr/bin/install -o root -g alfredpublish -m 0640 /var/lib/alfred-reviewer-state-v4/dev-v1-accept/T-0002/publication-handoff.json /var/lib/alfred-draft-pr-evidence/T-0002/publication-handoff.json
sudo /usr/bin/install -o root -g alfredpublish -m 0640 /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/qa-report.json /var/lib/alfred-draft-pr-evidence/T-0002/qa-report.json
sudo /usr/bin/install -o root -g alfredpublish -m 0640 /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/reviewer-handoff.json /var/lib/alfred-draft-pr-evidence/T-0002/reviewer-handoff.json
sudo /usr/bin/install -o root -g alfredpublish -m 0640 /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0002.json /var/lib/alfred-draft-pr-evidence/T-0002/cto-plan.json
sudo /usr/bin/install -o root -g alfredpublish -m 0640 /var/lib/alfred-development-grants/grant-445759a699d9423bbb5a8f1dd589689a.json /var/lib/alfred-draft-pr-evidence/T-0002/grant.json
sudo /usr/bin/install -o root -g alfredpublish -m 0640 /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo/.dev/tasks/T-0002-backend-calculator-subtract-helper.md /var/lib/alfred-draft-pr-evidence/T-0002/task-spec.md
sudo /usr/bin/install -o root -g alfredpublish -m 0640 /home/alfred/Git/alfred/registry/projects.yaml /var/lib/alfred-draft-pr-evidence/T-0002/projects.yaml
sudo /usr/bin/git clone --bare --no-local /var/lib/alfred-reviewer-snapshot /var/lib/alfred-draft-pr-evidence/T-0002/source.git
sudo /usr/bin/chown -R root:alfredpublish /var/lib/alfred-draft-pr-evidence/T-0002/source.git
sudo /usr/bin/chmod -R u=rwX,g=rX,o= /var/lib/alfred-draft-pr-evidence/T-0002/source.git
sudo /usr/bin/sha256sum /var/lib/alfred-draft-pr-evidence/T-0002/{review-report.json,publication-handoff.json,qa-report.json,reviewer-handoff.json}
sudo /usr/bin/sha256sum /home/alfred/Git/alfred/registry/projects.yaml /var/lib/alfred-draft-pr-evidence/T-0002/projects.yaml
```

The paired registry digests must match. Compare copied Reviewer and QA digests
to the originals from section 1. The `source.git` ownership and mode let the
publisher read Git objects without write access to the reviewed snapshot or
Developer worktrees. Supply a repository-scoped fine-grained GitHub token only
when preparing an authorized live publication; it needs Contents write and Pull
requests write for the one registered repository. Install it as
`/var/lib/alfred-draft-pr-private/github-token`, owned by `alfredpublish`, mode
0600. Never put it in the release, evidence handoff, command line, or another
agent's environment.

Check actual Linux permissions before preparation:

```sh
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test -r /var/lib/alfred-draft-pr-evidence/T-0002/review-report.json
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test -r /var/lib/alfred-draft-pr-evidence/T-0002/source.git/HEAD
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test ! -w /var/lib/alfred-draft-pr-evidence/T-0002/review-report.json
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test ! -w /var/lib/alfred-draft-pr-evidence/T-0002/source.git/HEAD
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test ! -r /var/lib/alfred-reviewer-state-v4/dev-v1-accept/T-0002/review-report.json
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test ! -r /var/lib/alfred-independent-qa-state/dev-v1-accept/T-0002/qa-report.json
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test ! -r /var/lib/alfred-development-grants/grant-445759a699d9423bbb5a8f1dd589689a.json
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test ! -w /var/lib/alfred-development-grants/grant-445759a699d9423bbb5a8f1dd589689a.json
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test ! -w /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0002.json
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/test ! -w /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final/calculator.py
```

## 3. Read-only publication preparation — administrator authorized run

Run the following as `alfredpublish` after the above evidence copies verify.
The command makes no GitHub request and cannot push. `-I` prevents importing
from the current directory or user site packages.

```sh
sudo /usr/sbin/runuser -u alfredpublish -- /usr/bin/python3 -I -B -c 'import sys; sys.path.insert(0, "/opt/alfred-draft-pr-publisher-v1"); from draft_pr_publisher.worker import main; raise SystemExit(main())' prepare --config /opt/alfred-draft-pr-publisher-v1/config.json --registry /var/lib/alfred-draft-pr-evidence/T-0002/projects.yaml --handoff /var/lib/alfred-draft-pr-evidence/T-0002/publication-handoff.json --review /var/lib/alfred-draft-pr-evidence/T-0002/review-report.json --qa /var/lib/alfred-draft-pr-evidence/T-0002/qa-report.json --qa-handoff /var/lib/alfred-draft-pr-evidence/T-0002/reviewer-handoff.json --plan /var/lib/alfred-draft-pr-evidence/T-0002/cto-plan.json --grant /var/lib/alfred-draft-pr-evidence/T-0002/grant.json --spec /var/lib/alfred-draft-pr-evidence/T-0002/task-spec.md --source-repo /var/lib/alfred-draft-pr-evidence/T-0002/source.git --output-root /var/lib/alfred-draft-pr-state
sudo /usr/bin/sha256sum /var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-plan.json
sudo /usr/bin/cat /var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-plan.json
```

The plan must name the registered destination and exact final revision. A
missing remote repository or a remote `main` that differs from the approved
baseline blocks publication. No substitute repository is permitted.

## 4. Separate owner authorization and live Draft PR — later action only

Use the existing trusted owner channel to obtain an explicit approval for one
Draft PR at the plan's exact digest, destination, branch, and revision. The
trusted administrator verifies that event, records its identifier in an
`alfred.github-draft-pr-authorization/1` JSON file matching
`schemas/owner-authorization.schema.json`, then installs it root-owned, 0640,
in `/var/lib/alfred-draft-pr-authorizations/T-0002.json`. A development grant
or an old owner approval is insufficient. The administrator separately installs
the dedicated token file, owner `alfredpublish`, mode 0600. Neither is created
by `prepare` or by the publisher.

Only after those separate actions, invoke the same command from section 3 with
`publish` in place of `prepare`, plus:

```sh
--authorization /var/lib/alfred-draft-pr-authorizations/T-0002.json --token-file /var/lib/alfred-draft-pr-private/github-token
```

Use the printed `publication-result.json` only when `status` is
`PUBLISHED_DRAFT`, `draft_pr_url` is under the registered repository, and
`commit` is the approved final revision. Its next stage is Alfred's completion
notification. An `ERROR` result requires operator investigation; retries do
not change the approved revision or destination.

## 5. Rollback

No service needs stopping. Stop invoking the publisher, remove the dedicated
token from use, and move the installed release to a protected archive. Preserve
the evidence handoff, authorization record, publication plan, result, and any
Draft PR for audit. Do not delete or rewrite Developer, QA, or Reviewer records.

```sh
sudo /usr/bin/install -d -o root -g root -m 0700 /var/lib/alfred-draft-pr-backups
sudo /bin/mv /opt/alfred-draft-pr-publisher-v1 /var/lib/alfred-draft-pr-backups/alfred-draft-pr-publisher-v1-rollback
sudo /bin/mv /var/lib/alfred-draft-pr-private/github-token /var/lib/alfred-draft-pr-backups/github-token-revoked
sudo /usr/bin/chown root:root /var/lib/alfred-draft-pr-backups/github-token-revoked
sudo /usr/bin/chmod 0600 /var/lib/alfred-draft-pr-backups/github-token-revoked
```

If a token was exposed or publication was attempted, revoke it at GitHub too.
If the protected backup target already exists, choose a new dated path before
moving anything. A Draft PR is never merged or closed by this rollback.
