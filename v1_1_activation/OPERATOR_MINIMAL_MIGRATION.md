# V1.1 minimum same-server migration — operator candidate

**Approval and host preflight required. Do not execute during staging review.** This procedure reuses the reviewed V1.1a Gateway patch, V1.1b Hermes/sidecar patch, corrected Spectrum patch, and the existing Photon project/line. It starts no second Photon connection. It does not authorize developer execution, GitHub publication, merge or deployment.

## Facts established and limits

The installed user unit starts Hermes as `alfred` from `/home/alfred/.hermes`. Its launcher has absolute paths to `/home/alfred/.hermes/hermes-agent` and `/home/alfred/.hermes/tools/python-3.14.7+20260901-linux-x64`; the sidecar uses `/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node` and pinned `@spectrum-ts/imessage` 12.7.0 under the installed Hermes source. Keeping this code path **readable but unwritable** to two new UIDs avoids a risky launcher rewrite or second SDK tree. The new Hermes *state home* moves to `/var/lib/alfredmsg/hermes`; its PM tool store is private at `/var/lib/alfredmsg/hermes/tools`. The dependency startup preflight in `HERMES_DEPENDENCY_STARTUP.md` is mandatory before stopping the old unit.

The existing `0600` `.env` contains the two Photon project keys and other provider keys. `auth.json` has `credential_pool.photon`, `photon_project`, `photon_user` and non-Photon providers. `config.yaml` has Photon enabled, but no inline project keys; `PHOTON_ALLOWED_USERS` is exactly one E.164 value. The sidecar record currently names port 8789 and a PID; the Hermes PID file and the user journal name the same Hermes start, but **the Codex PID namespace cannot see those host PIDs**. `systemctl --user` and `ss` returned `Operation not permitted`. A host operator must prove the record is live and tied to the unit before stopping it.

The installed `terminal.backend` and `.env` `TERMINAL_ENV` are both `local`. The host has the existing local backend and rootful Docker socket, but no installed rootless Hermes container backend. Keep `local` in the **new** sanitized home and `alfredmsg` unit so Personal Alfred retains ordinary terminal use. The new UID must **not** join the host `docker` group or receive its socket. Accepted ADR 0009 still requires Docker-only: the proposed narrow V1.1 exception in `ADR_MINIMUM_PROPOSED.md` needs explicit owner approval before cutover. Leave the old user unit and its local terminal operational until the reviewed migration window; if the new UID fails terminal acceptance, restore the old unit before enabling Gateway pickup.

## Protected input pins

The human approval record must independently pin these digests; a hash printed from writable staging is evidence only after comparison with that protected record.

| Input | SHA-256 |
| --- | --- |
| `v1_1a/patches/gateway-task-filing.proposed.patch` | `74b747b5ed672fe7b7fdf97d3fed40c6493dd896693ea48cca53232f5dbe5604` |
| `v1_1b/patches/hermes-photon-gateway-intake.proposed.patch` | `876a1042b27b47b9e6080ead2004b96e025f6b83fc1c728690533f6c24ae178a` |
| `patches/spectrum-native-reply-provenance.proposed.patch` | `62d280e45e66b6880bf4e37d46aafbbf7cd4340368c5f85e6821f62c3cc62552` |
| `v1_1b/trusted_intake.py` | `89d316f914bfa057c67a06fa52dcd9dbe48d46014e212026485e198b50130fc3` |
| `v1_1b/plugin/__init__.py` | `5a9994d2a8e57ae7925b3ff963647cddbda09c87fcb536951dbb691a3e3a3abe` |
| `v1_1b/plugin/plugin.yaml` | `5e00a4931c1d72b32fb9f0c60b49c6d7e34fb6a9d24807126c04d4598a2d06ef` |
| `v1_1a/fixture/registry.template.yaml` | `a691c385d04cd903fd52e07ade15a896530492cfbcbb4a00270ccad1fdc12e03` |
| `units/alfred-development-intake.service` | `88b6e947411a3839e50470ceb8383531af373fdf60a20827d30cc6e7601d0eb1` |
| `units/alfred-photon.service` | `4bbec0e039290103cdb389e21c11b2443996c363122bc9fd6237994af77c6cfc` |
| `units/alfred-hermes.service` | `487b113e351e8953ceb9d7f12d96c43d9eada4cdeb49ea58551938c07ba522de` |

`systemd-analyze verify units/*.service` succeeded under systemd 255; this was **syntax validation only**.

## 0. Host preflight — no changes

Run as the normal `alfred` login on the host. Stop if the active cgroup, PID, port, source commit or credentials differ. The commands display no token or credential value.

```sh
cd /home/alfred/alfred-development-lab/milestone2/task-a
sha256sum v1_1a/patches/gateway-task-filing.proposed.patch v1_1b/patches/hermes-photon-gateway-intake.proposed.patch patches/spectrum-native-reply-provenance.proposed.patch v1_1b/trusted_intake.py v1_1b/plugin/__init__.py v1_1b/plugin/plugin.yaml v1_1a/fixture/registry.template.yaml v1_1_activation/units/*.service
git -C /home/alfred/Git/alfred rev-parse HEAD
git -C /home/alfred/.hermes/hermes-agent rev-parse HEAD
git -C /home/alfred/Git/alfred status --porcelain
git -C /home/alfred/.hermes/hermes-agent status --porcelain
test ! -e /home/alfred/.hermes/hermes-agent/.git/hermes-update-pull
git -C /home/alfred/Git/alfred apply --check "$PWD/v1_1a/patches/gateway-task-filing.proposed.patch"
git -C /home/alfred/.hermes/hermes-agent apply --check "$PWD/v1_1b/patches/hermes-photon-gateway-intake.proposed.patch"
git -C /home/alfred/.hermes/hermes-agent apply --check "$PWD/patches/spectrum-native-reply-provenance.proposed.patch"
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID -p ControlGroup -p UnitFileState
systemctl --user cat hermes-gateway.service
jq '{pid,port}' /home/alfred/.hermes/runtime/photon-sidecar.json
jq '{pid,start_time,hermes_home}' /home/alfred/.hermes/gateway.pid
ps -p "$(jq -r .pid /home/alfred/.hermes/gateway.pid)" -o pid,ppid,uid,comm
ps -p "$(jq -r .pid /home/alfred/.hermes/runtime/photon-sidecar.json)" -o pid,ppid,uid,comm
cat "/proc/$(jq -r .pid /home/alfred/.hermes/runtime/photon-sidecar.json)/cgroup"
ss -ltnp '( sport = :8789 )'
python3 - <<'PY'
import http.client, json
from pathlib import Path
record = json.loads(Path('/home/alfred/.hermes/runtime/photon-sidecar.json').read_text())
if record.get('port') != 8789 or not isinstance(record.get('token'), str):
    raise SystemExit('unexpected sidecar record')
connection = http.client.HTTPConnection('127.0.0.1', 8789, timeout=2)
connection.request('POST', '/healthz', body='{}',
                   headers={'Content-Type':'application/json',
                            'x-hermes-sidecar-token':record['token']})
response = connection.getresponse()
if response.status != 200 or json.loads(response.read(1024)).get('ok') is not True:
    raise SystemExit('old sidecar health check failed')
print('old sidecar loopback health passed; token suppressed')
PY
stat -c '%A %U:%G %n' /home/alfred /home/alfred/.hermes /home/alfred/.hermes/.env /home/alfred/.hermes/auth.json /home/alfred/Git/alfred /home/alfred/Alfred/gateway
getent passwd alfredmsg alfredphoton
getent group alfredevidencero docker
```

Expected: Gateway HEAD `0086db5f2c9a41b66161559a11056e4d14138cf9`; Hermes HEAD `26610b09a5c4aead8d8dfb276ea33decf0d7fa46`; both status outputs empty; three patch checks zero; active old unit PID equals `gateway.pid`; sidecar record has port 8789, live sidecar UID 1000, same service cgroup, and sole 8789 listener. The `alfredmsg` and `alfredphoton` accounts may already exist after the failed pilot. Verify each has its dedicated home, `/usr/sbin/nologin`, a distinct UID and no privileged groups; do not recreate an existing account. If the live sidecar cannot be identified, **stop**. The unit file and PID records alone do not establish a live connection.

## 1. Prepare while the old connection stays running — approval required

Run after the owner approves the two ADR amendments, exact files/hashes, two locked UIDs, root-owned credential files, `dev-001` registry row, and a brief single-connection cutover. Keep approved hashes outside the writable staging tree. The following are candidate operator commands, not staging actions.

```sh
sudo -v
sudo install -d -o root -g root -m 0755 /etc/alfred-v1.1
sudo install -d -o root -g root -m 0700 /var/backups/alfred-v1.1
sudo install -d -o root -g root -m 0755 /usr/local/lib/alfred-v1.1
if ! getent passwd alfredmsg >/dev/null; then sudo useradd --system --user-group --no-create-home --home-dir /var/lib/alfredmsg --shell /usr/sbin/nologin alfredmsg; fi
if ! getent passwd alfredphoton >/dev/null; then sudo useradd --system --user-group --no-create-home --home-dir /var/lib/alfredphoton --shell /usr/sbin/nologin alfredphoton; fi
test "$(getent passwd alfredmsg | cut -d: -f6,7)" = /var/lib/alfredmsg:/usr/sbin/nologin
test "$(getent passwd alfredphoton | cut -d: -f6,7)" = /var/lib/alfredphoton:/usr/sbin/nologin
sudo install -d -o alfredmsg -g alfredmsg -m 0700 /var/lib/alfredmsg /var/lib/alfredmsg/hermes /var/lib/alfredmsg/media
sudo install -d -o alfredphoton -g alfredphoton -m 0700 /var/lib/alfredphoton
sudo setfacl -m u:alfredmsg:--x,u:alfredphoton:--x /home/alfred /home/alfred/.hermes
sudo setfacl -m u:alfredphoton:--x /var/lib/alfredmsg
sudo setfacl -m u:alfredphoton:r-x /var/lib/alfredmsg/media
sudo setfacl -d -m u:alfredphoton:r-- /var/lib/alfredmsg/media
```

These ACLs allow path traversal to the existing **read-only-to-new-UIDs** launcher, Python/Node binaries and SDK. Do not add either UID to group `alfred` or `docker`. Check `getfacl` and `runuser -u alfredmsg -- test ! -r /home/alfred/Git/alfred/registry/projects.yaml` before continuing.

Copy the approved patch/unit/plugin inputs into `/etc/alfred-v1.1` as root-owned, read-only files; hash **those copies** against the independently approved values before any patch application or service start. Install only the verified gate source to `/usr/local/lib/alfred-v1.1/trusted_intake.py` (root `0444`) and the three verified units to `/etc/systemd/system/` (root `0644`). Never run staging Python or Node as root. Back up the old user unit, both clean source revisions, the two Spectrum `dist/index.*` files and the protected registry before cutover. Leave the old unit and source running unchanged until step 2.

Concrete protected-copy and backup commands, run from the Task A directory after checking the protected approval record:

```sh
sudo install -o root -g root -m 0444 v1_1a/patches/gateway-task-filing.proposed.patch /etc/alfred-v1.1/gateway.patch
sudo install -o root -g root -m 0444 v1_1b/patches/hermes-photon-gateway-intake.proposed.patch /etc/alfred-v1.1/hermes.patch
sudo install -o root -g root -m 0444 patches/spectrum-native-reply-provenance.proposed.patch /etc/alfred-v1.1/spectrum.patch
sudo install -o root -g root -m 0444 v1_1b/trusted_intake.py /etc/alfred-v1.1/trusted_intake.py
sudo install -o root -g root -m 0444 v1_1b/plugin/__init__.py /etc/alfred-v1.1/plugin-init.py
sudo install -o root -g root -m 0444 v1_1b/plugin/plugin.yaml /etc/alfred-v1.1/plugin.yaml
sudo install -o root -g root -m 0444 v1_1a/fixture/registry.template.yaml /etc/alfred-v1.1/registry.template.yaml
sudo install -o root -g root -m 0444 v1_1_activation/units/alfred-development-intake.service /etc/alfred-v1.1/alfred-development-intake.service
sudo install -o root -g root -m 0444 v1_1_activation/units/alfred-photon.service /etc/alfred-v1.1/alfred-photon.service
sudo install -o root -g root -m 0444 v1_1_activation/units/alfred-hermes.service /etc/alfred-v1.1/alfred-hermes.service
sha256sum /etc/alfred-v1.1/gateway.patch /etc/alfred-v1.1/hermes.patch /etc/alfred-v1.1/spectrum.patch /etc/alfred-v1.1/trusted_intake.py /etc/alfred-v1.1/plugin-init.py /etc/alfred-v1.1/plugin.yaml /etc/alfred-v1.1/registry.template.yaml /etc/alfred-v1.1/*.service
sudo cp -a /home/alfred/.config/systemd/user/hermes-gateway.service /var/backups/alfred-v1.1/hermes-gateway.service
sudo cp -a /home/alfred/Git/alfred/registry/projects.yaml /var/backups/alfred-v1.1/projects.yaml
sudo tar -C /home/alfred/Git/alfred -cf /var/backups/alfred-v1.1/gateway-files.tar .dev/bin/taskspec.py .dev/bin/intake.py
sudo tar -C /home/alfred/.hermes/hermes-agent -cf /var/backups/alfred-v1.1/hermes-files.tar gateway/session_context.py gateway/run.py gateway/run_turn.py plugins/platforms/photon/adapter.py plugins/platforms/photon/sidecar/index.mjs plugins/platforms/photon/sidecar/node_modules/@spectrum-ts/imessage/dist/index.js plugins/platforms/photon/sidecar/node_modules/@spectrum-ts/imessage/dist/index.d.ts
sudo chmod 0600 /var/backups/alfred-v1.1/hermes-gateway.service /var/backups/alfred-v1.1/projects.yaml /var/backups/alfred-v1.1/gateway-files.tar /var/backups/alfred-v1.1/hermes-files.tar
systemctl --user is-enabled hermes-gateway.service | sudo tee /var/backups/alfred-v1.1/old-unit-enabled >/dev/null
sudo chmod 0600 /var/backups/alfred-v1.1/old-unit-enabled
sudo install -o root -g root -m 0444 /etc/alfred-v1.1/trusted_intake.py /usr/local/lib/alfred-v1.1/trusted_intake.py
sudo install -o root -g root -m 0644 /etc/alfred-v1.1/alfred-development-intake.service /etc/systemd/system/alfred-development-intake.service
sudo install -o root -g root -m 0644 /etc/alfred-v1.1/alfred-photon.service /etc/systemd/system/alfred-photon.service
sudo install -o root -g root -m 0644 /etc/alfred-v1.1/alfred-hermes.service /etc/systemd/system/alfred-hermes.service
```

The unit/template copies are data until systemd loads them; do not start them before the credential and path checks. A concurrent modification of writable staging during `install` is caught by hashing the protected copies. Stop on any hash mismatch or unexpected path type. The root backup directory is mode `0700`; no copied Node or JavaScript runs as root.

Create four root-owned `0600` credential files in `/etc/alfred-v1.1`: `project-id`, `project-secret`, `send-token`, `control-token`. Extract the two project values from the existing `.env` using a reviewed, literal key parser **without sourcing `.env` or printing values**; require exactly one nonempty occurrence of each. Generate fresh independent random send/control tokens to files without echoing them. The sidecar unit receives all four via `LoadCredential`; Hermes receives only `send-token`. The gate config at `/home/alfred/Alfred/gateway/v1-1-intake.json` is `0600` and owned by `alfred`; it has the one existing allowed owner candidate, both allocated numeric UIDs, port 8789, the send token, fixed bound intake path, Gateway journal directory and `/run/alfred-development-intake/intake.sock`. The first preview must prove that the gate saw this value as an original SDK `sender.id`; a model or Hermes session cannot supply it.

The following fixed parser runs under the approved root operator session. It parses exact assignment lines and never evaluates `.env` as shell code. It writes no value to stdout or argv.

```sh
sudo python3 -I - <<'PY'
import os, secrets, stat
from pathlib import Path
source = Path('/home/alfred/.hermes/.env')
info = source.lstat()
if not stat.S_ISREG(info.st_mode) or info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != 0o600:
    raise SystemExit('unexpected source credential file')
lines = source.read_text().splitlines()
root = Path('/etc/alfred-v1.1')
for key, name in [('PHOTON_PROJECT_ID','project-id'), ('PHOTON_PROJECT_SECRET','project-secret')]:
    values = [line.split('=',1)[1] for line in lines if line.startswith(key + '=')]
    if len(values) != 1 or not values[0] or any(c.isspace() for c in values[0]):
        raise SystemExit('missing or ambiguous Photon key: ' + key)
    fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(values[0] + '\n'); stream.flush(); os.fsync(stream.fileno())
for name in ('send-token','control-token'):
    fd = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(secrets.token_hex(32) + '\n'); stream.flush(); os.fsync(stream.fileno())
directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
try: os.fsync(directory)
finally: os.close(directory)
print('four protected credential files created; values suppressed')
PY
sudo stat -c '%A %U:%G %n' /etc/alfred-v1.1/project-id /etc/alfred-v1.1/project-secret /etc/alfred-v1.1/send-token /etc/alfred-v1.1/control-token
```

All four must be regular files, root-owned and `0600`. If interrupted, inspect and remove only the incomplete pilot files before retrying; never overwrite a value blindly. The first protected preview must prove the candidate `PHOTON_ALLOWED_USERS` matched the original SDK sender before permitting a confirmation to file.

Precopy the old Hermes home to `/var/lib/alfredmsg/hermes` with `rsync -a --chown=alfredmsg:alfredmsg`, excluding `hermes-agent/`, `tools/`, `installs/`, backups, logs, `.env*`, `auth.json`, and the old runtime records. Do not take the final copy of live SQLite state yet. The copied `config.yaml`, `SOUL.md`, profiles, sessions, pending messages, media caches, Kanban/memory state and existing `alfred_development_status` plugin remain for ordinary conversation and Evidence Bridge. The new home must have no old Photon project secret in credential files, backups or runtime records.

Use the same command once now and once after the old unit stops, before making new-home edits:

```sh
sudo rsync -a --chown=alfredmsg:alfredmsg --exclude='hermes-agent/' --exclude='tools/' --exclude='installs/' --exclude='backups/' --exclude='.curator_backups/' --exclude='plugin-rollbacks/' --exclude='logs/' --exclude='lsp/' --exclude='sandboxes/' --exclude='terminal-sessions/' --exclude='pastes/' --exclude='source-checks/' --exclude='telemetry/' --exclude='runtime/' --exclude='.env*' --exclude='auth.json' --exclude='*.pre-*' --exclude='*.lock' --exclude='gateway.pid' --exclude='gateway.sock' --exclude='gateway_state.json' --exclude='gateway-starts.log' --exclude='processes.json' /home/alfred/.hermes/ /var/lib/alfredmsg/hermes/
sudo install -d -o alfredmsg -g alfredmsg -m 0700 /var/lib/alfredmsg/hermes/workspace
sudo stat -c '%A %U:%G %n' /var/lib/alfredmsg/hermes /var/lib/alfredmsg/hermes/config.yaml /var/lib/alfredmsg/hermes/SOUL.md /var/lib/alfredmsg/hermes/plugins/alfred_development_status
```

Before stopping the working user unit, complete `HERMES_DEPENDENCY_STARTUP.md` under separate host authorization. Its final transient probe must invoke the exact pinned Hermes launcher as `alfredmsg` with `HERMES_HOME=/var/lib/alfredmsg/hermes` and the proposed filesystem restrictions. Require a committed new-home environment and exit 0 while the old Hermes and Photon service is still active. A failure blocks cutover. Then run this **operator-authorized** transient systemd terminal probe. It uses the proposed UID and the Hermes unit's filesystem restrictions, but has no Photon or Gateway credentials and does not start Hermes. Expect `terminal-ok` and `workspace-ok`, exit 0, and no residual `.v11-terminal-preflight` file. This proves the proposed UID can run an ordinary shell command and use its private workspace; the actual Hermes tool must still pass the service-cgroup check after cutover.

```sh
sudo systemd-run --unit=alfred-v11-terminal-preflight --wait --collect --pipe \
  -p User=alfredmsg -p Group=alfredmsg -p SupplementaryGroups=alfredevidencero \
  -p WorkingDirectory=/var/lib/alfredmsg/hermes -p UMask=0077 \
  -p NoNewPrivileges=yes -p PrivateTmp=yes -p ProtectHome=read-only \
  -p ProtectSystem=strict -p ReadWritePaths=/var/lib/alfredmsg \
  /bin/bash -c 'set -eu; test "$(id -un)" = alfredmsg; test "$(pwd)" = /var/lib/alfredmsg/hermes; printf terminal-ok; cd workspace; printf workspace-ok > .v11-terminal-preflight; test "$(cat .v11-terminal-preflight)" = workspace-ok; rm .v11-terminal-preflight; test ! -e .v11-terminal-preflight; test ! -r /home/alfred/Git/alfred/registry/projects.yaml; test ! -w /home/alfred/Alfred/gateway; test ! -w /home/alfred/Alfred/projects/hermes-requests/inbox; test ! -w /home/alfred/alfred-development-lab/repo/.dev/tasks; test ! -w /var/run/docker.sock'
```

## 2. Short cutover window — approval required

With Gateway pickup still disabled, record the original user unit's enabled state, then run:

```sh
systemctl --user disable --now hermes-gateway.service
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID
ss -ltnp '( sport = :8789 )'
```

Expected: old unit inactive, old sidecar PID exited, port 8789 free. Stop if the sidecar remains alive; never start the replacement while it exists. Final-sync the copied Hermes state after the old process exits, using the same exclusions. Build the new home `.env` by removing `PHOTON_PROJECT_ID` and `PHOTON_PROJECT_SECRET`; preserve its existing `TERMINAL_ENV=local` and other provider keys. The new unit also sets `TERMINAL_ENV=local`, matching `config.yaml`, so startup and per-turn config reloads select the same backend. Build the new `auth.json` by deleting `credential_pool.photon`, `credential_pool.photon_project`, `credential_pool.photon_user` and legacy `providers.photon`, preserving other providers. Both files must be owned by `alfredmsg` mode `0600`; confirm the removed Photon key names are absent without printing values. Keep the original home and credentials untouched for rollback.

After rerunning the `rsync` command above, create only the sanitized files. The `installs/` and `tools/` exclusions retain the independently committed new-home dependency state. The sanitized-file command fails if either destination already exists, so an interrupted attempt needs inspection before retry:

```sh
sudo python3 -I - <<'PY'
import json, os, pwd, stat
from pathlib import Path
source = Path('/home/alfred/.hermes')
target = Path('/var/lib/alfredmsg/hermes')
uid = pwd.getpwnam('alfredmsg').pw_uid
gid = pwd.getpwnam('alfredmsg').pw_gid
raw = (source / '.env').read_text()
kept = [line for line in raw.splitlines() if not line.startswith(('PHOTON_PROJECT_ID=', 'PHOTON_PROJECT_SECRET='))]
if len(kept) != len(raw.splitlines()) - 2 or [line for line in kept if line.startswith('TERMINAL_ENV=')] != ['TERMINAL_ENV=local']:
    raise SystemExit('unexpected Photon or terminal key count')
auth = json.loads((source / 'auth.json').read_text())
pool = auth.get('credential_pool', {})
for key in ('photon', 'photon_project', 'photon_user'):
    pool.pop(key, None)
auth.get('providers', {}).pop('photon', None)
def put(name, data):
    fd = os.open(target / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchown(fd, uid, gid)
    with os.fdopen(fd, 'w') as out:
        out.write(data); out.flush(); os.fsync(out.fileno())
put('.env', '\n'.join(kept) + '\n')
put('auth.json', json.dumps(auth, separators=(',', ':')) + '\n')
print('sanitized Hermes credential files created; values suppressed')
PY
sudo -u alfredmsg python3 -I - <<'PY'
import json
from pathlib import Path
home = Path('/var/lib/alfredmsg/hermes')
lines = (home/'.env').read_text().splitlines()
assert all(not line.startswith(('PHOTON_PROJECT_ID=', 'PHOTON_PROJECT_SECRET=')) for line in lines)
assert [line for line in lines if line.startswith('TERMINAL_ENV=')] == ['TERMINAL_ENV=local']
auth = json.loads((home/'auth.json').read_text())
assert not {'photon','photon_project','photon_user'} & set(auth.get('credential_pool', {}))
assert 'photon' not in auth.get('providers', {})
print('Photon credentials absent from new structured credential files')
PY
```

Before starting the new Hermes unit, the operator must also scan the copied home for the exact protected project ID and secret **without printing them**. Scan regular files in chunks and reject symlinks that leave the new home. A hit is a stop condition requiring review of that copied file; do not delete arbitrary session state automatically. This closes the possibility that a historical backup or session embeds a Photon credential despite the structured-file exclusions. The scan itself must run only in the protected operator session.

```sh
sudo python3 -I - <<'PY'
from pathlib import Path
root = Path('/var/lib/alfredmsg/hermes').resolve()
needles = tuple(Path('/etc/alfred-v1.1', n).read_bytes().strip() for n in ('project-id','project-secret'))
if not all(needles): raise SystemExit('missing protected comparison value')
overlap = max(map(len, needles)) - 1
for path in root.rglob('*'):
    if path.is_symlink():
        if not path.resolve(strict=False).is_relative_to(root):
            raise SystemExit('copied home has an external symlink: ' + str(path))
        continue
    if path.is_dir(): continue
    if not path.is_file(): raise SystemExit('unexpected copied file type: ' + str(path))
    with path.open('rb') as stream:
        tail = b''
        while chunk := stream.read(1024 * 1024):
            data = tail + chunk
            if any(needle in data for needle in needles):
                raise SystemExit('Photon credential found in copied home: ' + str(path))
            tail = data[-overlap:] if overlap else b''
print('copied home has no protected project credential bytes or external symlink')
PY
```

In the **new** `config.yaml` only, enable plugin `alfred_development_gateway_intake` and append that toolset to `platform_toolsets.photon`; retain `terminal.backend: local`. Copy the reviewed plugin files under `/var/lib/alfredmsg/hermes/plugins/alfred_development_gateway_intake` and add the approved one-paragraph natural-language intake instruction from `v1_1b/README.md` to the new `SOUL.md`. Do not register this toolset for other platforms or profiles. Verify the new YAML parses and the old config remains byte-identical. Create a private terminal workspace owned by `alfredmsg`; it is separate from the Gateway and `dev-001` task repository.

```sh
sudo install -d -o alfredmsg -g alfredmsg -m 0700 /var/lib/alfredmsg/hermes/plugins/alfred_development_gateway_intake
sudo install -o alfredmsg -g alfredmsg -m 0644 /etc/alfred-v1.1/plugin-init.py /var/lib/alfredmsg/hermes/plugins/alfred_development_gateway_intake/__init__.py
sudo install -o alfredmsg -g alfredmsg -m 0644 /etc/alfred-v1.1/plugin.yaml /var/lib/alfredmsg/hermes/plugins/alfred_development_gateway_intake/plugin.yaml
sudo -u alfredmsg python3 - <<'PY'
from pathlib import Path
import yaml
p = Path('/var/lib/alfredmsg/hermes/config.yaml')
cfg = yaml.safe_load(p.read_text())
name = 'alfred_development_gateway_intake'
enabled = cfg['plugins']['enabled']
photon = cfg['platform_toolsets']['photon']
if not isinstance(enabled, list) or not isinstance(photon, list) or name in enabled or name in photon:
    raise SystemExit('unexpected plugin configuration')
enabled.append(name)
photon.append(name)
if cfg['terminal']['backend'] != 'local':
    raise SystemExit('original local terminal backend changed')
with p.open('w') as out:
    yaml.safe_dump(cfg, out, sort_keys=False)
    out.flush()
print('new Hermes config updated; old config unchanged')
PY
sudo -u alfredmsg tee -a /var/lib/alfredmsg/hermes/SOUL.md >/dev/null <<'EOF'

## V1.1 Development intake
When the authenticated owner naturally requests a software change for dev-001, prepare a faithful draft and call development_gateway_submit for that original Photon turn. Tell the owner to reply directly to the protected preview with “Yes, go ahead”; do not say a task was filed at the preview stage. On a confirmation turn, call development_gateway_status and report a task ID only when it returns filed with task_id. Continue ordinary conversation otherwise. On expiry, uncertainty or rejection, ask for a fresh owner request. Filing does not approve execution.
EOF
sudo -u alfredmsg python3 -c 'import yaml; from pathlib import Path; d=yaml.safe_load(Path("/var/lib/alfredmsg/hermes/config.yaml").read_text()); assert d["terminal"]["backend"]=="local" and "alfred_development_gateway_intake" in d["plugins"]["enabled"] and "alfred_development_gateway_intake" in d["platform_toolsets"]["photon"]'
```

The `SOUL.md` append is one-shot; on an interrupted attempt, check for the `V1.1 Development intake` marker before repeating. The operator reviews the new config diff against the old config, with secret values redacted from any shared evidence.

Repeat the confined launcher probe from `HERMES_DEPENDENCY_STARTUP.md` after the final sync, credential sanitization and plugin configuration, before enabling any new service. A dependency sync, repair, or failed exit at this point blocks cutover and triggers rollback.

Apply the root-controlled approved V1.1a patch to `/home/alfred/Git/alfred`, and the V1.1b and native Spectrum patches to `/home/alfred/.hermes/hermes-agent`, **as user `alfred`** after `git apply --check`. Install the already reviewed `dev-001` registry row from `v1_1a/fixture/registry.template.yaml` with `local_path: /home/alfred/alfred-development-lab/repo`; create only that repo's `.dev/tasks` directory. Keep `/ship` and other task-ID writers excluded during the pilot. Do not alter Gateway approval or execution policy.

```sh
sudo -u alfred git -C /home/alfred/Git/alfred apply --check /etc/alfred-v1.1/gateway.patch
sudo -u alfred git -C /home/alfred/.hermes/hermes-agent apply --check /etc/alfred-v1.1/hermes.patch
sudo -u alfred git -C /home/alfred/.hermes/hermes-agent apply --check /etc/alfred-v1.1/spectrum.patch
sudo -u alfred git -C /home/alfred/Git/alfred apply /etc/alfred-v1.1/gateway.patch
sudo -u alfred git -C /home/alfred/.hermes/hermes-agent apply /etc/alfred-v1.1/hermes.patch
sudo -u alfred git -C /home/alfred/.hermes/hermes-agent apply /etc/alfred-v1.1/spectrum.patch
sudo install -d -o alfred -g alfred -m 0700 /home/alfred/Alfred/projects /home/alfred/Alfred/projects/hermes-requests /home/alfred/Alfred/projects/hermes-requests/inbox
sudo install -d -o alfred -g alfred -m 0755 /home/alfred/alfred-development-lab/repo/.dev /home/alfred/alfred-development-lab/repo/.dev/tasks
```

The registry update is one atomic replacement under `alfred`, with a same-directory fsync. It stops if `dev-001` already exists or the lab repo has a Git remote; review the resulting row before any Gateway pickup:

```sh
sudo -u alfred python3 - <<'PY'
import os, tempfile, yaml
from pathlib import Path
path = Path('/home/alfred/Git/alfred/registry/projects.yaml')
template = Path('/etc/alfred-v1.1/registry.template.yaml').read_text()
fixture = yaml.safe_load(template)['projects'][0]
if (fixture['id'] != 'dev-001' or fixture['company'] != 'alfred'
        or fixture['permissions']['hermes_requests'] is not True
        or fixture['local_path'] != 'FIXTURE_REPO_PATH'):
    raise SystemExit('wrong fixture')
fixture['local_path'] = '/home/alfred/alfred-development-lab/repo'
old = path.read_text()
registry = yaml.safe_load(old)
if any(p.get('id') == 'dev-001' for p in registry['projects']): raise SystemExit('dev-001 already registered')
if old.count('projects:\n') != 1 or template.count('projects:\n') != 1 or not old.endswith('\n'):
    raise SystemExit('unexpected registry layout')
row = template.split('projects:\n', 1)[1].replace('FIXTURE_REPO_PATH', fixture['local_path'])
candidate = old + row
checked = yaml.safe_load(candidate)
if checked['projects'] != registry['projects'] + [fixture]: raise SystemExit('registry merge mismatch')
fd, name = tempfile.mkstemp(prefix='.projects-v1-1-', dir=path.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'w') as out:
        out.write(candidate); out.flush(); os.fsync(out.fileno())
    os.replace(name, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)
finally:
    if os.path.exists(name): os.unlink(name)
print('dev-001 registry row installed; no task filed')
PY
```

The operator must run `git -C /home/alfred/alfred-development-lab/repo remote -v` before this block and require no output. No GitHub remote is added.

Create the gate config from the existing single allowed owner value and the protected send token. The value is a **candidate** until the live original-event preview succeeds; never use a model-provided identifier:

```sh
sudo python3 -I - <<'PY'
import json, os, pwd, re
from pathlib import Path
source = Path('/home/alfred/.hermes/.env').read_text().splitlines()
owner = [line.split('=',1)[1] for line in source if line.startswith('PHOTON_ALLOWED_USERS=')]
if len(owner) != 1 or not re.fullmatch(r'\+[1-9][0-9]{6,14}', owner[0]):
    raise SystemExit('one E.164 owner allowlist entry required')
send_token = Path('/etc/alfred-v1.1/send-token').read_text().strip()
if len(send_token) != 64: raise SystemExit('missing send token')
gate = pwd.getpwnam('alfred')
sidecar = pwd.getpwnam('alfredphoton')
hermes = pwd.getpwnam('alfredmsg')
if len({gate.pw_uid, sidecar.pw_uid, hermes.pw_uid}) != 3: raise SystemExit('UIDs must differ')
config = dict(owner_sender_id=owner[0], sidecar_uid=sidecar.pw_uid,
              hermes_uid=hermes.pw_uid, sidecar_port=8789, sidecar_token=send_token,
              intake_dir='/home/alfred/Alfred/projects/hermes-requests',
              gateway_dir='/home/alfred/Alfred/gateway',
              socket_path='/run/alfred-development-intake/intake.sock')
path = Path('/home/alfred/Alfred/gateway/v1-1-intake.json')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
os.fchown(fd, gate.pw_uid, gate.pw_gid)
with os.fdopen(fd, 'w') as out:
    json.dump(config, out, separators=(',', ':')); out.write('\n')
    out.flush(); os.fsync(out.fileno())
print('gate config created; identity and token suppressed')
PY
sudo stat -c '%A %U:%G %n' /home/alfred/Alfred/gateway/v1-1-intake.json
```

Do not display this JSON in logs or review evidence. Its parent is the existing protected Gateway directory, still mode `0700` owned by `alfred`.

```sh
sudo systemd-analyze verify /etc/systemd/system/alfred-development-intake.service /etc/systemd/system/alfred-photon.service /etc/systemd/system/alfred-hermes.service
sudo systemctl daemon-reload
sudo systemctl enable --now alfred-development-intake.service
sudo systemctl enable --now alfred-photon.service
sudo systemctl enable --now alfred-hermes.service
systemctl --user show hermes-gateway.service -p ActiveState -p UnitFileState
```

Expected: all new units active, old unit inactive/disabled, one sidecar on 8789, gate socket present. The new Hermes unit still uses the existing pinned launcher and SDK files, but with `HERMES_HOME=/var/lib/alfredmsg/hermes`, `TERMINAL_ENV=local` and `PHOTON_SIDECAR_EXTERNAL=true`; it does not spawn another sidecar. If any unit fails or ordinary messaging or terminal acceptance does not return promptly, roll back before enabling Gateway pickup. The original home, `terminal.backend: local` and user unit remain intact for rollback.

## 3. Minimum acceptance, then one authorized filing

Before any real Gateway run, verify unit UIDs with `systemctl show -p User -p MainPID`, socket ACLs with `stat`/`getfacl`, and negative DAC checks with `runuser -u alfredmsg -- test ! -r` or `test ! -w` on the Gateway registry, journal, approval state, bound inbox and `dev-001/.dev/tasks`. Verify gate `SO_PEERCRED` treats `alfredphoton` as observation-only and `alfredmsg` as draft/status-only; a direct Hermes confirmation request must fail. The gate socket parent must be owned by `alfred` and not writable by clients. Test one ordinary owner text exchange and one photo, voice and document send/receive via the **one** Photon connection; check Evidence Bridge v0.2.1 status under the new Hermes UID.

Before that intake test, verify ordinary Personal Alfred terminal use **inside the actual new Hermes service** through the same owner Photon conversation. The first owner request is: “Run `id -un; pwd; cat /proc/self/cgroup; printf terminal-ok` in your terminal and report the output.” Expected: `alfredmsg`, a cgroup containing `alfred-hermes.service`, `/var/lib/alfredmsg/hermes` and `terminal-ok`. The second request is: “Run `cd /var/lib/alfredmsg/hermes/workspace && printf v1.1-ok > terminal-acceptance.txt && cat terminal-acceptance.txt && rm terminal-acceptance.txt && test ! -e terminal-acceptance.txt` and report the output.” Expected: `v1.1-ok`, no residual acceptance file, no task or repository write. If the terminal tool requires its normal user confirmation, approve only these benign commands. In the same service-bound terminal, run `test ! -r /home/alfred/Git/alfred/registry/projects.yaml && test ! -w /home/alfred/Alfred/gateway && test ! -w /home/alfred/Alfred/projects/hermes-requests/inbox && test ! -w /home/alfred/alfred-development-lab/repo/.dev/tasks && test ! -w /var/run/docker.sock` and require exit 0. Also require that `alfredmsg` lacks the `docker` group. If any positive or negative check fails, stop before Gateway pickup and roll back.

These host commands return success only if the essential DAC boundary holds. The short IPC probes carry no owner identity, message content or valid event handle and must produce `wrong_peer` or `missing_turn_binding`; they cannot file a request:

```sh
sudo systemctl show alfred-development-intake.service alfred-photon.service alfred-hermes.service -p User -p MainPID -p ActiveState
sudo id -nG alfredmsg
sudo id -nG alfredphoton
sudo stat -c '%F %A %U:%G %n' /run/alfred-development-intake /run/alfred-development-intake/intake.sock /home/alfred/Alfred/projects/hermes-requests/inbox
sudo getfacl -cp /run/alfred-development-intake /run/alfred-development-intake/intake.sock /var/lib/alfredmsg/media
sudo getfacl -cp /var/run/docker.sock
sudo runuser -u alfredmsg -- test ! -r /home/alfred/Git/alfred/registry/projects.yaml
sudo runuser -u alfredmsg -- test ! -r /home/alfred/Alfred/gateway
sudo runuser -u alfredmsg -- test ! -w /home/alfred/Alfred/gateway
sudo runuser -u alfredmsg -- test ! -r /home/alfred/Alfred/projects/hermes-requests/inbox
sudo runuser -u alfredmsg -- test ! -w /home/alfred/Alfred/projects/hermes-requests/inbox
sudo runuser -u alfredmsg -- test ! -w /home/alfred/alfred-development-lab/repo/.dev/tasks
sudo runuser -u alfredmsg -- test ! -r /etc/alfred-v1.1/project-secret
sudo runuser -u alfredmsg -- test ! -r /etc/alfred-v1.1/control-token
sudo runuser -u alfredmsg -- test -w /var/lib/alfredmsg/hermes/workspace
sudo runuser -u alfredmsg -- test ! -w /var/run/docker.sock
sudo runuser -u alfredmsg -- python3 -c 'import json,socket; s=socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect("/run/alfred-development-intake/intake.sock"); s.sendall(b"{\"op\":\"observe\",\"event\":{}}\n"); print(json.loads(s.recv(1024))["error"])'
sudo runuser -u alfredphoton -- python3 -c 'import json,socket; s=socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect("/run/alfred-development-intake/intake.sock"); s.sendall(b"{\"op\":\"submit\"}\n"); print(json.loads(s.recv(1024))["error"])'
```

Expected new-UID group lists exclude `alfred`, `docker`, `alfreddevipc` and `alfredauthipc`. Expected last two lines: `wrong_peer`, `wrong_peer`. Any access denial test returning nonzero is a hard stop, as is a missing socket or wrong unit UID. The gate process may read the fixed Gateway journal; Hermes may obtain status only through the gate. No privileged dev-executor service, Evidence Bridge publisher or Gateway authorization state is modified.

For the separately approved intake acceptance, the owner sends one natural-language development request, receives the exact gate preview, and directly replies `Yes, go ahead` to that preview. Confirm an unthreaded or wrong-target reply does not publish. Confirm exactly one `alfred.devreq/1` file appears **only after** the correct original SDK reply. The operator then runs the single approved Gateway `run-once` for the bound inbox; verify one canonical `proposed` task in the `dev-001` lab repo and the real task ID returned to Alfred. A duplicate confirmation must not create another task. No execution or GitHub command follows. If native direct target equality or explicit `nativeIsForward=false` is unavailable live, intake fails closed; preserve ordinary messaging and roll back intake activation.

The one protected filing command, **only after the owner separately authorizes this live acceptance and confirms the inbox contains exactly the intended envelope**, is:

```sh
cd /home/alfred/Git/alfred
PYTHONDONTWRITEBYTECODE=1 /home/alfred/Git/alfred/.venv/bin/python .dev/bin/gateway.py validate-registry
PYTHONDONTWRITEBYTECODE=1 /home/alfred/Git/alfred/.venv/bin/python .dev/bin/gateway.py status
PYTHONDONTWRITEBYTECODE=1 /home/alfred/Git/alfred/.venv/bin/python .dev/bin/gateway.py run-once
PYTHONDONTWRITEBYTECODE=1 /home/alfred/Git/alfred/.venv/bin/python .dev/bin/gateway.py status
```

Run as `alfred`, never as `alfredmsg`. Expected `run-once` output is one `filed T-NNNN (proposed, needs Hayden's approval)` and no approval or execution. Preserve the exact task ID and journal outcome for review. A second `run-once` after duplicate delivery must file zero new tasks.

## 4. Targeted rollback

Disable Gateway pickup first. Keep any filed task and journal record for audit. Stop new services in this order and verify 8789 is free:

```sh
sudo systemctl disable --now alfred-hermes.service
sudo systemctl disable --now alfred-photon.service
sudo systemctl disable --now alfred-development-intake.service
ss -ltnp '( sport = :8789 )'
```

Reverse the protected source patches after the new processes exit. If a reverse check fails, stop and restore the exact source-file tar backups under protected review; do not force a partial reverse. The original user unit and original Hermes home remain in place throughout this pilot.

```sh
sudo -u alfred git -C /home/alfred/.hermes/hermes-agent apply -R --check /etc/alfred-v1.1/spectrum.patch
sudo -u alfred git -C /home/alfred/.hermes/hermes-agent apply -R --check /etc/alfred-v1.1/hermes.patch
sudo -u alfred git -C /home/alfred/Git/alfred apply -R --check /etc/alfred-v1.1/gateway.patch
sudo -u alfred git -C /home/alfred/.hermes/hermes-agent apply -R /etc/alfred-v1.1/spectrum.patch
sudo -u alfred git -C /home/alfred/.hermes/hermes-agent apply -R /etc/alfred-v1.1/hermes.patch
sudo -u alfred git -C /home/alfred/Git/alfred apply -R /etc/alfred-v1.1/gateway.patch
```

If reverse application cannot proceed, the separately approved **backup fallback** restores only the exact originally modified files and removes only the three files that these patches added. Verify the snapshot and that no service/dispatcher is active first:

```sh
sudo tar -C /home/alfred/.hermes/hermes-agent -xf /var/backups/alfred-v1.1/hermes-files.tar
sudo tar -C /home/alfred/Git/alfred -xf /var/backups/alfred-v1.1/gateway-files.tar
sudo rm -f -- /home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/development-observe.mjs /home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/restricted-media.mjs /home/alfred/Git/alfred/.dev/task-id-reservations.txt
git -C /home/alfred/.hermes/hermes-agent status --porcelain
git -C /home/alfred/Git/alfred status --porcelain
```

The final two outputs must contain no unexpected changes before restarting the old unit. This fallback is for an interrupted pilot only; it is not a general source reset.

Revert only the approved Hermes and SDK patches as `alfred` after `git apply -R --check`; restore the backed-up exact files if reverse application fails. If **no** canonical task was filed, restore the original registry from the protected backup after Gateway pickup is stopped. If a task was filed, retain the registry row, journal and task for audit and obtain a separate protected disposition. The old Hermes home/unit were never rewritten. Restart only the old user unit after the new sidecar has exited:

```sh
sudo install -o alfred -g alfred -m 0600 /var/backups/alfred-v1.1/projects.yaml /home/alfred/Git/alfred/registry/projects.yaml
```

The registry restore line applies **only when no task was filed**. Recheck its original hash before executing it.

```sh
systemctl --user start hermes-gateway.service
if [ "$(sudo cat /var/backups/alfred-v1.1/old-unit-enabled)" = enabled ]; then systemctl --user enable hermes-gateway.service; fi
systemctl --user show hermes-gateway.service -p ActiveState -p MainPID -p UnitFileState
ss -ltnp '( sport = :8789 )'
```

Expected: the original user unit and its single child sidecar are back, normal text/media and Evidence Bridge work, and new units remain disabled. Retain the pilot credentials, account IDs and snapshot until the owner reviews the incident; remove only pilot-specific state in a separately approved cleanup. Never delete a canonical task to disguise a partial filing.

Restore the exact saved dependency-access ACLs from `HERMES_DEPENDENCY_STARTUP.md` after the old unit is active. Do not remove or repair the original dependency store. Retain the new home's failed PM state for diagnosis.

## Exact approval and host gates

1. Owner approval of the proposed ADR 0003 Phase 4 and ADR 0009 narrow intake changes, V1.1a/ADR 0011 lab allocation, the protected `dev-001` registry row, and the one-request acceptance.
2. Owner approval of the two stable service UIDs, root-owned credential/backup files, source patch application, three system units, brief old-unit stop and controlled new-unit start. The approved record must pin the patches, gate/plugin files and final unit hashes separately from staging.
3. Host operator proof of **live** old unit/sidecar/cgroup/port, source cleanliness, original SDK owner sender ID, credential key inventory, copied-home privacy, socket peer UIDs/ACLs, Gateway denial, and ordinary text/media before filing. These cannot be completed from the Codex sandbox.
4. Explicit owner approval of the narrow ADR 0009 local-terminal exception for `alfredmsg`, conditional on the ordinary command, private workspace write, service-cgroup and protected-path denial checks above. The old `terminal.backend: local` remains operational until the approved cutover; restore it immediately if the new service fails these checks. Do not grant the new UID host Docker authority as a shortcut.

No installation, restart, credential copy, Photon connection or real filing was performed in preparing this document.

## Staging validation performed

`systemd-analyze verify` accepted the revised Hermes unit on systemd 255; the two other staged units were verified previously and are unchanged. The focused terminal staging tests passed **2/2**, including an ordinary command and a private workspace create/read/delete using the pinned `LocalEnvironment` and runtime dependencies as the staging UID. The three reviewed patches each passed `git apply --check` against the pinned clean Gateway/Hermes sources in the earlier migration check. The staged sidecar passed full Node syntax checking. All 21 shell blocks and eight inline Python blocks in this revised procedure parsed. A read-only in-memory check confirmed that the proposed registry append preserves the existing row and adds exactly the pinned `dev-001` row; the installed credential/config key shapes matched the sanitization commands. These checks do not establish service startup, new-UID terminal behavior or permissions, live Photon behavior or Gateway pickup.
