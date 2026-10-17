# First live Backend Developer acceptance

> **Status, 2026-10-17: historical.** This runbook prepared the first
> operator-fixture acceptance, and that has since run. `dev-v1-accept` is in the
> production registry (`projects.yaml` now equals `projects.proposed.yaml`, so the
> baseline `cmp` below fails, as expected). T-0002 reached a draft PR, which was
> merged on GitHub as `596d91d`. T-0003 (`multiply`) is held and must not be
> touched. `verify_preparation.py` now predicts T-0004. For the remaining live
> gates, use [verification/PHASE_D_CHECKLIST.md](../verification/PHASE_D_CHECKLIST.md)
> from the merged checkout `/home/alfred/alfred-development-v1`.

This is a preparation and future operator runbook. No live task has been filed,
no iMessage sent, no development grant issued, and no developer invoked.

## What is ready now

The disposable Git repository is `repo/`, project `dev-v1-accept`, baseline
`9000574c4c8807e84c4350e2fd342deeba341d7d`. `calculator.py` has `add`;
the existing focused test passes `test_add` and intentionally fails
`test_subtract` until one method is added. `.dev/task-id-reservations.txt`
reserves T-0001, so an otherwise empty repository starts at T-0002. Nothing
under `dev-001` or its T-0001 was changed.

`projects.proposed.yaml` is the current protected registry plus exactly one
new project. The proposed GitHub slug is a schema placeholder; no remote or
publisher is used. `gateway-envelope.fixture.json` is explicitly an
**operator-authored acceptance fixture**, not a Photon owner observation. It
must be placed in the bound Gateway inbox only with separate operator approval.
That filing validates Gateway/CTO/Developer execution, while the later
development grant is a real native threaded owner approval through Photon.

The installed ordinary Intake has `PROJECT = "dev-001"`. An owner iMessage
asking for `dev-v1-accept` would still create a `dev-001` envelope. **Do not
send such a request.** A full owner-confirmed initial filing for the new
project requires a separate, narrowly reviewed Intake project-selection
change and Intake restart. This runbook uses the disclosed operator fixture
for the first Developer-only acceptance, and does not claim to test the full
Personal Alfred intake chain.

## Preparation checks — safe now

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
cmp live-acceptance/projects.baseline.yaml /home/alfred/Git/alfred/registry/projects.yaml
diff -u live-acceptance/projects.baseline.yaml live-acceptance/projects.proposed.yaml
git -C live-acceptance/repo status --porcelain
git -C live-acceptance/repo rev-parse HEAD
/home/alfred/Git/alfred/.venv/bin/python live-acceptance/verify_preparation.py
/home/alfred/Git/alfred/.venv/bin/python live-acceptance/verify_gateway_fixture.py
codex login status
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl show -p ActiveState -p Result alfred-development-gateway.service alfred-development-gateway.timer
test -f /opt/alfred-developer-v1/active
```

The two verification scripts are read-only against production. The Gateway
dry run uses a temporary copy of the repository, registry, inbox, journal and
CTO plan; its sender returns a fixture ID and sends no message. PASS requires
T-0002, one filed task, one clarification-free plan, only `backend`, and
authenticated Codex status. Installed Backend config selects `codex/gpt-6-sol`
with high reasoning, `codex/gpt-6.1-sol` fallback, and cost limit 2 policy
units. Authentication and configured routing pass; the provider's acceptance
of `gpt-6-sol` cannot be proved without a model call. Treat provider rejection
as a live acceptance failure, with only the approved fallback permitted.

## Gate A — register and file the operator fixture

**Do not run without explicit authorization to change the protected registry,
file this test task, and permit the CTO to send its plan iMessage.** The current
registry must still equal `projects.baseline.yaml`; if it drifted, stop and
regenerate/review the proposal. The backup is created before replacement.

```bash
set -e
cd /home/alfred/alfred-development-lab/milestone2/task-a
sudo cmp live-acceptance/projects.baseline.yaml /home/alfred/Git/alfred/registry/projects.yaml
sudo test ! -e /home/alfred/Git/alfred/registry/projects.yaml.pre-dev-v1-accept
sudo cp -p /home/alfred/Git/alfred/registry/projects.yaml /home/alfred/Git/alfred/registry/projects.yaml.pre-dev-v1-accept
sudo cmp /home/alfred/Git/alfred/registry/projects.yaml.pre-dev-v1-accept live-acceptance/projects.baseline.yaml
sudo install -o alfred -g alfred -m 0600 live-acceptance/projects.proposed.yaml /home/alfred/Git/alfred/registry/projects.yaml
sudo test ! -e /home/alfred/Alfred/projects/hermes-requests/inbox/dev-v1-accept-fixture.json
sudo install -o alfred -g alfred -m 0600 live-acceptance/gateway-envelope.fixture.json /home/alfred/Alfred/projects/hermes-requests/inbox/dev-v1-accept-fixture.json
sudo systemctl start alfred-development-gateway.service
```

The final command runs Gateway once and CTO `ExecStartPost`; it may send one
plan iMessage. Do not repeat it to try an uncertain send. Inspect the Gateway
journal and plan before continuing:

```bash
sudo -u alfred jq -e 'select(.kind=="outcome" and .outcome=="filed" and .project=="dev-v1-accept" and .task_id=="T-0002" and .request_id=="b6d51fb2-2586-4cd5-a5c2-e3578f273d20")' /home/alfred/Alfred/gateway/journal.jsonl
sudo -u alfred env PYTHONPATH=/home/alfred/Git/alfred/.dev/bin:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B /home/alfred/Git/alfred/.dev/bin/cto.py show T-0002 --project dev-v1-accept
sudo -u alfred jq -e '.clarification_required==false and .approval_state=="awaiting_development_approval" and .repository=="/home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo"' /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0002.json
sudo -u alfred sha256sum /home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0002.json
```

If filing or planning differs, stop. The actual task ID and exact plan bytes,
not the synthetic preview, govern approval. A clarification-required plan
cannot be staged for development.

## Gate B — native owner development approval

**Do not run without separate authorization to send a live Photon challenge.**
Use the protected CTO delivery config's owner DM space ID without reading or
printing its token:

```bash
set -e
OWNER_DM_SPACE_ID=$(sudo -u alfred jq -r '.owner_space_id' /home/alfred/Alfred/gateway/v1-cto-delivery.json)
sudo -u alfred /usr/bin/python3 -c 'import hashlib; from pathlib import Path; p=Path("/home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0002.json"); print("Approve development dev-v1-accept T-0002 " + hashlib.sha256(p.read_bytes()).hexdigest()[:12])'
sudo env PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.stage_approval --socket /run/alfred-development-intake/intake.sock --project dev-v1-accept --task T-0002 --worktree-root /var/lib/alfred-development-worktrees --scope calculator.py --space-id "$OWNER_DM_SPACE_ID"
```

The returned `challenge` is the prospective grant reference, but **is not a
grant yet**. The owner must reply directly to this challenge iMessage, within
five minutes, with exactly the phrase it displays:

`Approve development dev-v1-accept T-0002 <first 12 hex digits of exact plan SHA-256>`

It must be a native threaded reply to the challenge message, not the earlier
CTO plan message. Intake verifies SDK sender, DM, reply target, non-forward,
phrase and freshness. No grant is issued for clarification. Record the
reference privately and verify that `grant-<reference>.json` appears in
`/var/lib/alfred-development-grants` before Gate C.

## Gate C — create private request and execute one Backend assignment

**Do not run without separate authorization for this real developer task.**
The helper reads the canonical Gateway task/plan, rechecks the exact owner
grant, and writes a mode 0600 request under the alfred-owned 0700 state root.
It asks for the reference on a hidden terminal prompt; do not put it in an
argument, world-readable file, or chat message.

```bash
set -e
sudo -u alfred env PYTHONPATH=/opt/alfred-developer-v1:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/write_run_request.py --task T-0002
sudo -u alfred env PYTHONPATH=/home/alfred/Git/alfred/src:/opt/alfred-developer-v1 /home/alfred/Git/alfred/.venv/bin/python -B -m developer_v1.run_task --request /var/lib/alfred-development-state/request-dev-v1-accept-T-0002.json --models /var/lib/alfred-development-state/models.json --gateway-root /home/alfred/Git/alfred --gateway-state /home/alfred/Alfred/gateway --registry /home/alfred/Git/alfred/registry/projects.yaml --grant-root /var/lib/alfred-development-grants --state-root /var/lib/alfred-development-state
```

The request template has one `backend-subtract` assignment and only
`calculator.py` in scope. The real worker creates task-specific worktrees,
edits only that file through bubblewrap, runs unittest discovery in a
read-only namespace, makes an authorized local commit, and writes a report
plus QA manifest. It has no merge, deployment, or GitHub publishing step.

## Inspect evidence and duplicate denial

```bash
sudo -u alfred jq -e '.status=="completed" and .specialist=="backend" and .assigned_scope==["calculator.py"] and .model_used.provider=="codex" and (.files_modified|length)==1 and (.commits|length)==1 and (.tests|all(.outcome=="passed")) and .qa_handoff.ready==true' /var/lib/alfred-development-state/dev-v1-accept/T-0002/report-backend-subtract.json
sudo -u alfred jq -e '.state=="ready_for_independent_qa" and .project=="dev-v1-accept" and .task_id=="T-0002" and (.developer_reports|length)==1' /var/lib/alfred-development-state/dev-v1-accept/T-0002/qa-input.json
sudo -u alfred git -C /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-backend-subtract log -1 --format='%H %s'
sudo -u alfred git -C /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final log -1 --format='%H %s'
sudo -u alfred git -C /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final diff HEAD^ HEAD --name-only
sudo -u alfred sha256sum /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final/calculator.py
sudo -u alfred git -C /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo diff -- calculator.py
FILE_SHA=$(sudo -u alfred sha256sum /var/lib/alfred-development-worktrees/dev-v1-accept-T-0002-final/calculator.py | cut -d' ' -f1)
sudo -u alfred jq -e --arg file_sha "$FILE_SHA" '.status=="completed" and .files_modified==[{"path":"calculator.py","sha256":$file_sha}] and .qa_handoff.changed_file_hashes["calculator.py"]==$file_sha and (.tests|any(.outcome=="passed" and (.evidence|startswith("exit=0;"))))' /var/lib/alfred-development-state/dev-v1-accept/T-0002/report-backend-subtract.json
sudo -u alfred jq -e --arg file_sha "$FILE_SHA" '.changed_file_hashes["calculator.py"]==$file_sha and .final_revision!=""' /var/lib/alfred-development-state/dev-v1-accept/T-0002/qa-input.json
```

PASS requires only `calculator.py` in the final diff, the file SHA-256 equal
to `qa-input.json.changed_file_hashes.calculator.py` and the report hash,
`subtract(7,3)==4`, `add(7,3)==10`, an isolated test outcome `passed` with
exit zero in its evidence, and nonempty commit references. The registered
source repository's `calculator.py` must remain unchanged. QA consumes the
manifest later; no QA, reviewer, or publisher is run here.

For duplicate prevention, record the report and branch heads, then rerun the
same Gate C **runner command only**. It must exit nonzero before a second
model invocation; the report, commit and final branch head must not change.
Do not create another request or grant for this check.

Read-only baseline and host-health checks after the run:

```bash
git -C /home/alfred/alfred-development-lab/milestone2/task-a/live-acceptance/repo status --porcelain
systemctl is-active alfred-development-intake.service alfred-photon.service alfred-hermes.service
systemctl show -p ActiveState -p Result alfred-development-gateway.service alfred-development-gateway.timer
```

## Gate A recovery — only after a failed or uncertain result

Do not repeat the fixture installation or `systemctl start`. First inspect the
append-only Gateway journal for request
`b6d51fb2-2586-4cd5-a5c2-e3578f273d20`, the disposable repository's
`.dev/tasks/`, and any `dev-v1-accept-*.json` CTO plan. If a task was filed,
**keep the proposed registry registered**: removing its binding would make the
canonical task and plan unresolvable. Preserve the task, journal, plan, and
processed/rejected envelope as audit evidence. A missing CTO plan after a filed
task needs a separately authorized CTO recovery; do not refile the fixture.

For an existing plan, inspect `delivery.state` and `delivery.message_id`.
`delivered` means a message was acknowledged. `attempted_uncertain` means a
send may have occurred: reconcile the existing message before any further
action. `pending` means a future CTO poll may send it. None of these states
authorizes a repeat Gateway start or CTO poll. A clarification or filing
rejection also remains in the journal; do not replay the same request ID and
revision. Any new attempt needs a newly reviewed fixture and authorization.

Restore the previous registry **only if no canonical task, filed journal
outcome, CTO plan, grant, developer state, or worktree uses `dev-v1-accept`**.
The command below holds the Gateway lock, requires its service and timer to be
inactive, requires the current registry to match `projects.proposed.yaml`
byte for byte, and validates the original mode `0600` backup against
`projects.baseline.yaml`. It preserves a still-pending inbox fixture in a
private recovery directory before restoring. Any failed check stops recovery;
investigate instead of deleting audit artifacts or forcing a reset.

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
sudo flock -n /home/alfred/Alfred/gateway/lock /bin/bash -euc '
  cd /home/alfred/alfred-development-lab/milestone2/task-a
  registry=/home/alfred/Git/alfred/registry/projects.yaml
  backup=/home/alfred/Git/alfred/registry/projects.yaml.pre-dev-v1-accept
  inbox=/home/alfred/Alfred/projects/hermes-requests/inbox/dev-v1-accept-fixture.json
  held=/home/alfred/Alfred/projects/hermes-requests/recovery/dev-v1-accept-fixture.json
  journal=/home/alfred/Alfred/gateway/journal.jsonl
  test "$(systemctl show -p ActiveState --value alfred-development-gateway.service)" = inactive
  test "$(systemctl show -p ActiveState --value alfred-development-gateway.timer)" = inactive
  test -f "$backup" && test ! -L "$backup"
  test -f "$registry" && test ! -L "$registry"
  test "$(stat -c "%a %U:%G" "$backup")" = "600 alfred:alfred"
  test "$(stat -c "%a %U:%G" "$registry")" = "600 alfred:alfred"
  cmp live-acceptance/projects.baseline.yaml "$backup"
  cmp live-acceptance/projects.proposed.yaml "$registry"
  revision=$(git -C live-acceptance/repo rev-parse HEAD)
  test "$revision" = 9000574c4c8807e84c4350e2fd342deeba341d7d
  changes=$(git -C live-acceptance/repo status --porcelain)
  test -z "$changes"
  task=$(find live-acceptance/repo/.dev/tasks -maxdepth 1 -name "T-*.md" -print -quit)
  test -z "$task"
  filed=$(jq -s --arg project dev-v1-accept --arg rid b6d51fb2-2586-4cd5-a5c2-e3578f273d20 "any(.[]; .kind==\"outcome\" and .outcome==\"filed\" and (.project==\$project or .request_id==\$rid))" "$journal")
  test "$filed" = false
  plan=$(find /home/alfred/Alfred/gateway/cto-plans -maxdepth 1 -name "dev-v1-accept-*.json" -print -quit)
  test -z "$plan"
  test ! -e /var/lib/alfred-development-state/dev-v1-accept
  worktree=$(find /var/lib/alfred-development-worktrees -maxdepth 1 -name "dev-v1-accept-*" -print -quit)
  test -z "$worktree"
  for record in /var/lib/alfred-development-grants/*.json; do
    test -e "$record" || continue
    project=$(jq -r "(.request.project // .project) // empty" "$record")
    test "$project" != dev-v1-accept
  done
  if test -e "$inbox" || test -L "$inbox"; then
    test -f "$inbox" && test ! -L "$inbox"
    cmp live-acceptance/gateway-envelope.fixture.json "$inbox"
    test ! -e "$held" && test ! -L "$held"
    test ! -L "$(dirname "$held")"
    install -d -o alfred -g alfred -m 0700 "$(dirname "$held")"
    test "$(stat -c "%a %U:%G" "$(dirname "$held")")" = "700 alfred:alfred"
    mv -- "$inbox" "$held"
  fi
  cmp live-acceptance/projects.proposed.yaml "$registry"
  install -o alfred -g alfred -m 0600 "$backup" "$registry"
  cmp live-acceptance/projects.baseline.yaml "$registry"
  cmp "$backup" "$registry"
  echo "PASS: previous registry restored; audit evidence retained"
'
```

This changes only the acceptance project's registry addition and, if needed,
moves its unprocessed fixture to protected holding. The original backup remains
untouched; the restored bytes include the existing `dev-001` binding and leave
T-0001 alone. A partially completed restore requires another read-only state
review; do not force this command past its exact-registry check.
