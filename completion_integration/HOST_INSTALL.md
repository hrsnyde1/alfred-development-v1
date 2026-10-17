# Completion notification: minimal host installation

Operator procedure only; these commands have not been executed. Install code
and prepare a disabled handoff. This does not authorize an iMessage. No service
is added or restarted. The notifier runs on demand as the existing Intake
identity `alfred`, and calls the existing Photon sidecar at its configured port.
Keep the existing Developer, QA, Reviewer, Publisher, Gateway, Photon, credentials,
and evidence in place.

## 1. Install the reviewed library

Run from `/home/alfred/alfred-development-lab/milestone2/task-a`. Abort on any
failed check. The literal manifest pin verifies both the staging inventory and
the protected copies. Only the six named runtime files and their manifest are
installed; the Mac archive, tests, and inspection evidence are excluded.

```sh
(
set -eu
printf '%s  %s\n' 'e315211f3c8e13d05e81598d77d9e64c0d92d3690cf186d9826968913eacde82' 'completion_integration/release.sha256' | sha256sum -c -
(cd completion_integration && sha256sum -c release.sha256)
sudo /usr/bin/test ! -e /usr/local/lib/alfred-completion-v1
sudo /usr/bin/install -d -o root -g root -m 0755 /usr/local/lib/alfred-completion-v1/completion_integration
sudo /usr/bin/install -o root -g root -m 0644 completion_integration/__init__.py completion_integration/completion.py completion_integration/delivery.py completion_integration/runtime.py completion_integration/publication-result.schema.json completion_integration/config.example.json completion_integration/release.sha256 /usr/local/lib/alfred-completion-v1/completion_integration/
printf '%s  %s\n' 'e315211f3c8e13d05e81598d77d9e64c0d92d3690cf186d9826968913eacde82' '/usr/local/lib/alfred-completion-v1/completion_integration/release.sha256' | sudo /usr/bin/sha256sum -c -
sudo /bin/sh -c 'cd /usr/local/lib/alfred-completion-v1/completion_integration && /usr/bin/sha256sum -c release.sha256'
)
```

Use the existing `/home/alfred/Git/alfred/.venv/bin/python` interpreter with
its existing Pydantic 2 and jsonschema installations. Local tests ran with
Python 3.14.7, Pydantic 2.13.5 and pytest 9.1.1. No dependency installation is
needed. The runtime also uses the already installed `gh` and its existing
operator credentials for GET requests only. It does not read the Publisher's
GitHub token.

## 2. Prepare read-only snapshots of genuine publication inputs

An administrator must read the protected Publisher files. This session could
not read their hashes because sudo required a password. Do not substitute test
results, invented event IDs, requester outbox content, or an earlier ERROR.
Verify the installed Publisher V1.1 manifest and copy its existing successful
result, exact plan, and separate authorization without altering the originals.

```sh
(
set -eu
printf '%s  %s\n' '926c925fedcaad40ef9240c2558ff9d10f241329f290a99e212a449f1c66442e' '/opt/alfred-draft-pr-publisher-v1/release.sha256' | sudo /usr/bin/sha256sum -c -
sudo /bin/sh -c 'cd /opt/alfred-draft-pr-publisher-v1 && /usr/bin/sha256sum -c release.sha256'
sudo /usr/bin/test ! -e /etc/alfred-completion-v1
sudo /usr/bin/install -d -o root -g alfred -m 0750 /etc/alfred-completion-v1
sudo /usr/bin/install -o root -g alfred -m 0640 /var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-result.json /etc/alfred-completion-v1/publication-result.json
sudo /usr/bin/install -o root -g alfred -m 0640 /var/lib/alfred-draft-pr-state/dev-v1-accept/T-0002/publication-plan.json /etc/alfred-completion-v1/publication-plan.json
sudo /usr/bin/install -o root -g alfred -m 0640 /var/lib/alfred-draft-pr-authorizations/T-0002.json /etc/alfred-completion-v1/owner-authorization.json
printf '%s  %s\n' '511fa533fd9dc5bb41d51bff1baa21b28a54b8b0b670e5b3f0f602a78d38b903' '/etc/alfred-completion-v1/publication-plan.json' | sudo /usr/bin/sha256sum -c -
)
```

The following reviewed standard-library block builds a disabled configuration
from those snapshots and the genuine matching native publication-approval DM.
It reads no token value into the new configuration and prints no identities or
credentials. `owner_merge_attested=True` records the owner's explicit statement
in this task that the subsequent T-0002 merge was a separate authorized owner
action. GitHub's merging account alone would not establish that authority.
This block creates configuration, not a publication authorization record.

```sh
sudo /usr/bin/python3 -I -B <<'PREPARE_COMPLETION_CONFIG'
import hashlib
import json
import os
import re
from pathlib import Path

target = Path('/etc/alfred-completion-v1')
installed = Path('/usr/local/lib/alfred-completion-v1/completion_integration')
config = json.loads((installed / 'config.example.json').read_bytes())
objects = {}
for name in ('publication-result', 'publication-plan', 'owner-authorization'):
    raw = (target / (name + '.json')).read_bytes()
    objects[name] = json.loads(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if name == 'publication-plan':
        assert digest == config['publication-plan-sha256'], 'Wrong approved plan'
    config[name + '-sha256'] = digest
plan, result, auth = (objects[k] for k in
                     ('publication-plan', 'publication-result', 'owner-authorization'))
binding = config['binding']
assert all(plan.get(k) == v for k, v in binding.items())
assert result['schema'] == 'alfred.draft-pr-result/1'
assert result['status'] == 'PUBLISHED_DRAFT' and result['detail'] is None
assert result['next_stage'] == 'alfred_completion_notification'
assert result['draft_pr_url'] == 'https://github.com/hrsnyde1/alfred-dev-v1-acceptance/pull/1'
assert result['commit'] == binding['final_revision']
assert all(result.get(k) == binding[k] for k in binding if k != 'final_revision')
assert all(result[k] == plan[k] for k in ('qa_report_sha256', 'review_report_sha256'))
assert auth == {'schema': 'alfred.github-draft-pr-authorization/1', 'decision': 'approved',
                'purpose': 'one_github_draft_pr', **binding,
                'publication_plan_sha256': config['publication-plan-sha256'],
                'owner_event_id': auth['owner_event_id']}
assert isinstance(auth['owner_event_id'], str) and auth['owner_event_id'].strip()
assert result['publication_plan_sha256'] == config['publication-plan-sha256']

intake = json.loads(Path('/home/alfred/Alfred/gateway/v1-1-intake.json').read_bytes())
store = Path(intake['development_grant_root'])
matches = [json.loads(p.read_bytes()) for p in store.glob('publication-decision-*.json')]
matches = [d for d in matches if d.get('owner_event_id') == auth['owner_event_id']]
assert len(matches) == 1, 'No unique genuine publication decision'
decision = matches[0]
reference = decision['reference']
assert re.fullmatch('[0-9a-f]{32}', reference)
receipt = json.loads((store / ('publication-challenge-' + reference + '.json')).read_bytes())
assert receipt['schema'] == 'alfred.publication-challenge/1'
assert receipt['plan_sha256'] == config['publication-plan-sha256']
assert all(receipt.get(k) == v for k, v in binding.items())
assert receipt['owner_id'] == decision['sender_id'] == intake['owner_sender_id']
assert decision['space_id'] == receipt['space_id']
assert decision['direction'] == 'inbound' and decision['is_forward'] is False
assert decision['native_reply_target'] == receipt['message_id']
assert decision['owner_event_id'] != receipt['message_id']
assert all(decision['checks'].get(k) is True for k in
           ('authenticated_sender', 'same_dm', 'native_direct_reply', 'not_forwarded'))
assert decision['challenge_sha256'] == hashlib.sha256(
    json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
config.update(enabled=False, owner_sender_id=receipt['owner_id'],
              owner_space_id=receipt['space_id'], owner_merge_attested=True)
fd = os.open(target / 'config.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
with os.fdopen(fd, 'w') as stream:
    json.dump(config, stream, indent=2, sort_keys=True)
    stream.write('\n')
    stream.flush()
    os.fsync(stream.fileno())
PREPARE_COMPLETION_CONFIG
```

After the block succeeds:

```sh
sudo /usr/bin/chown root:alfred /etc/alfred-completion-v1/config.json
sudo /usr/bin/chmod 0640 /etc/alfred-completion-v1/config.json
```

If any preparation command fails, leave sending disabled. Inspect partial
handoff files; do not rerun first-install steps over an existing configuration.

## 3. Initialize durable tracking once, then preview

Only for a genuinely new notification installation with no prior delivery:

```sh
(
set -eu
sudo /usr/bin/test ! -e /home/alfred/Alfred/completion-delivery
sudo /usr/bin/install -d -o alfred -g alfred -m 0700 /home/alfred/Alfred/completion-delivery
sudo /usr/sbin/runuser -u alfred -- /home/alfred/Git/alfred/.venv/bin/python -I -B -c 'import sys; sys.path.insert(0, "/usr/local/lib/alfred-completion-v1"); from completion_integration.runtime import main; raise SystemExit(main())' initialize
)
```

Reuse existing tracking on upgrades. Never initialize after lost state; restore
or reconcile prior attempts first. A dedicated fixed owner DM and this same
state directory must persist across releases. Do not prune or replace the
directory, lock file, or records.

Preview performs a current read-only GitHub GET and verifies all pinned inputs;
it sends nothing and creates no delivery record:

```sh
sudo /usr/sbin/runuser -u alfred -- /home/alfred/Git/alfred/.venv/bin/python -I -B -c 'import sys; sys.path.insert(0, "/usr/local/lib/alfred-completion-v1"); from completion_integration.runtime import main; raise SystemExit(main())' preview
```

The installed default remains disabled. There is no installation-time `notify`
command. A separately authorized completion caller may later enable the root
configuration and invoke the same entrypoint with mode `notify`. That mode
checks PAUSE before preparation and immediately before its send callback. It
rechecks GitHub rather than sending saved preview text. No Gateway state
transition or automatic publication retry is performed.

`sent` means the existing Photon sidecar returned HTTP 200, literal `ok:true`,
and a nonempty valid `messageId` after awaiting its SDK send. The receipt is
persisted. It does not mean recipient delivery/read. Missing IDs, timeouts,
errors, crashes, or failure to save success retain `uncertain`; no automatic
retry or reset is provided. Investigate via existing Photon records/owner
reconciliation. Changed text for the same publication identity also blocks
resending, even when GitHub state changes.

## Rollback

Stop invoking this on-demand completion entrypoint and leave its configuration
disabled (set `enabled` to false if it was separately enabled). No service
restart is needed. Preserve the installed library, protected input snapshots,
configuration, delivery directory, receipts, and lock file for review. A later
upgrade can replace only reviewed library files while retaining that state.
Do not remove credentials or rewrite any Developer, QA, Reviewer, Publisher,
Photon, Gateway, authorization, plan, or publication-result records.
