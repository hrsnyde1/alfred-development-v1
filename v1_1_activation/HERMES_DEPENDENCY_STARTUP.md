# V1.1 Hermes dependency startup — operator candidate

**Preparation only. Do not run these host commands without separate migration approval.** Keep the original `hermes-gateway.service` and its Photon child running throughout this preflight. No command below starts a second Photon connection or invokes the Development Gateway.

## Cause and supported path

The pinned launcher uses `HERMES_HOME` to select `<home>/installs/e1541360de565941/facts.json` and its committed venv (`pm/environments.py:27-38,299-319,449-483`). `/var/lib/alfredmsg/hermes` has no valid committed venv. Copying only the original `facts.json` is invalid: its absolute environment path points outside the new install. The original venv's executable and libraries being readable does not supply the new home's lock, lease and selection state. Borrowed launches explicitly sync their **own** dependency environment (`hermes_cli/venv_sync.py:452-483`).

The installed `install-stamp.json` is `0600`, owned by `alfred`, with no named-user read ACL. `pm/runtime.py:68-79` reports an unreadable stamp as `invalid package install stamp`. Fix its read access for `alfredmsg`; do not copy or rewrite its contents. Keep the original PM store read-only to `alfredmsg`: PM's tool operations acquire writable store locks. Use PM's `stage_tools` API to copy and verify the pinned tool closure into a private store, then let PM create a **new** committed venv from the copied uv cache. This preserves validation and prevents writes to Personal Alfred's original dependency state. It may locally reconstruct a venv; zero-copy sharing is not supported across these two homes.

The staging sandbox cannot enter UID `alfredmsg` or its protected home. These are candidate operator commands, not evidence that the new service starts.

## Before the old service is stopped

These commands require the separately approved host migration. First verify the old service is active, the new service is inactive, the source installation ID is the pinned one, and the protected backup directory exists. Stop if any condition differs. Do not print credential values.

```sh
test "$(systemctl --user is-active hermes-gateway.service)" = active
test "$(sudo systemctl is-active alfred-hermes.service)" != active
sudo stat -c '%F %a %U:%G %n' /home/alfred/.hermes/hermes-agent/install-stamp.json /home/alfred/.hermes/tools/facts.json /home/alfred/.hermes/installs/e1541360de565941/facts.json
sudo test -f /home/alfred/.hermes/hermes-agent/install-stamp.json
sudo test ! -L /home/alfred/.hermes/hermes-agent/install-stamp.json
sudo test -f /home/alfred/.hermes/tools/facts.json
sudo test ! -L /home/alfred/.hermes/tools/facts.json
sudo test -f /home/alfred/.hermes/installs/e1541360de565941/facts.json
sudo test ! -L /home/alfred/.hermes/installs/e1541360de565941/facts.json
sudo test -d /var/backups/alfred-v1.1
sudo test -d /var/lib/alfredmsg/hermes
sudo test ! -L /var/lib/alfredmsg/hermes
sudo sh -c 'sha256sum /home/alfred/.hermes/tools/facts.json /home/alfred/.hermes/installs/e1541360de565941/facts.json > /var/backups/alfred-v1.1/original-dependencies.sha256'
sudo chmod 0600 /var/backups/alfred-v1.1/original-dependencies.sha256
```

Both assertions must exit 0; the old unit must be active and the new unit must not be active. The two fact files and source stamp must be regular files. The backed-up SHA-256 list is root controlled. Verify the independently approved source and unit digests from `OPERATOR_MINIMAL_MIGRATION.md` before any copy or unit start.

Back up the current ACLs, then grant only traversal of the existing source parents and read access to its non-secret install stamp. The original service remains untouched. If either `alfredmsg` read check fails, stop.

```sh
sudo sh -c 'getfacl -p /home/alfred /home/alfred/.hermes /home/alfred/.hermes/hermes-agent/install-stamp.json > /var/backups/alfred-v1.1/dependency-access.acl'
sudo chmod 0600 /var/backups/alfred-v1.1/dependency-access.acl
sudo test -s /var/backups/alfred-v1.1/dependency-access.acl
sudo setfacl -m u:alfredmsg:--x /home/alfred /home/alfred/.hermes
sudo setfacl -m u:alfredmsg:r-- /home/alfred/.hermes/hermes-agent/install-stamp.json
sudo -u alfredmsg test -r /home/alfred/.hermes/hermes-agent/install-stamp.json
sudo -u alfredmsg test -x /home/alfred/.hermes/hermes-agent/.hermes/bin/hermes
```

If the failed automatic repair left `installs/e1541360de565941` or a private `tools` directory in the new home, move each whole directory to the protected backup area before trying again. This retains `.repair-incomplete` and any copied invalid fact for diagnosis. Never edit either fact by hand. Stop if a backup destination already exists or a source is a symlink.

```sh
sudo test ! -e /var/backups/alfred-v1.1/failed-alfredmsg-install
sudo test ! -e /var/backups/alfred-v1.1/failed-alfredmsg-tools
sudo test ! -L /var/lib/alfredmsg/hermes/installs/e1541360de565941
sudo test ! -L /var/lib/alfredmsg/hermes/tools
if sudo test -d /var/lib/alfredmsg/hermes/installs/e1541360de565941; then sudo mv -T -- /var/lib/alfredmsg/hermes/installs/e1541360de565941 /var/backups/alfred-v1.1/failed-alfredmsg-install; fi
if sudo test -d /var/lib/alfredmsg/hermes/tools; then sudo mv -T -- /var/lib/alfredmsg/hermes/tools /var/backups/alfred-v1.1/failed-alfredmsg-tools; fi
sudo install -d -o alfredmsg -g alfredmsg -m 0700 /var/lib/alfredmsg/hermes/installs /var/lib/alfredmsg/hermes/cache/uv
```

Use the **installed** PM's `stage_tools` API as `alfred`, never root. It verifies the original lock, fact, tool bytes and link targets, and produces its own destination fact. The included `uv` is an internal dependency of the new venv. The staging destination must be new and private. The root operator only moves and changes ownership of the completed data; no copied executable runs as root.

```sh
sudo test ! -e /var/lib/alfred-v11-tool-stage
sudo install -d -o alfred -g alfred -m 0700 /var/lib/alfred-v11-tool-stage
sudo -u alfred env -i HOME=/home/alfred PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /home/alfred/.hermes/installs/e1541360de565941/environments/4c916e3798f64707827a0687c843a14f/venv/bin/python -I -B - <<'PY'
import sys
sys.path.insert(0, '/home/alfred/.hermes/hermes-agent')
from pm.build_operations import stage_tools
from pm.lock import Lockfile
from pm.registry import tool_roots
from pm.store import current_target
root = '/home/alfred/.hermes/hermes-agent'
names = [*tool_roots(Lockfile(root + '/pm/lock.json').names()), 'uv']
stage_tools(names, source_store='/home/alfred/.hermes/tools', out='/var/lib/alfred-v11-tool-stage', target=current_target())
print('verified private tool closure staged:', ','.join(names))
PY
sudo test -f /var/lib/alfred-v11-tool-stage/facts.json
sudo chown -R --no-dereference alfredmsg:alfredmsg /var/lib/alfred-v11-tool-stage
sudo mv -T -- /var/lib/alfred-v11-tool-stage /var/lib/alfredmsg/hermes/tools
sudo -u alfredmsg test -r /var/lib/alfredmsg/hermes/tools/facts.json
sudo sha256sum -c /var/backups/alfred-v1.1/original-dependencies.sha256
```

Copy the existing uv cache into the new private home. The cache is only an optimization: the pinned lock and PM verification remain authoritative. The following PM install runs with all IP traffic denied. A cache miss or required download must fail the preflight and leave the old service running. It reproduces the original recorded extras `all` and `anthropic` without installing optional default tools.

```sh
sudo rsync -a --chown=alfredmsg:alfredmsg /home/alfred/.hermes/cache/uv/ /var/lib/alfredmsg/hermes/cache/uv/
sudo systemd-run --unit=alfred-v11-pm-preflight --wait --collect --pipe \
  -p User=alfredmsg -p Group=alfredmsg -p SupplementaryGroups=alfredevidencero \
  -p RuntimeMaxSec=900 \
  -p WorkingDirectory=/var/lib/alfredmsg/hermes -p UMask=0077 \
  -p Environment=HERMES_HOME=/var/lib/alfredmsg/hermes \
  -p Environment=HERMES_RUNTIME_DIR=/var/lib/alfredmsg/hermes/tools \
  -p Environment=UV_NO_INDEX=1 -p IPAddressDeny=any \
  -p NoNewPrivileges=yes -p PrivateTmp=yes -p ProtectHome=read-only \
  -p ProtectSystem=strict -p ReadWritePaths=/var/lib/alfredmsg \
  -p RestrictAddressFamilies='AF_UNIX AF_INET AF_INET6' \
  /home/alfred/.hermes/hermes-agent/.hermes/bin/hermes pm install --extra all --extra anthropic
```

Require exit 0. A local venv sync may copy cached wheels or build the local Hermes package; this procedure does not claim zero rebuilding. It guarantees no provider download **only if** the host confirms `IPAddressDeny=any` was enforced. Keep Gateway pickup disabled. Read the new PM fact under the new UID and require its selected environment to be inside the new install state. The stale `.repair-incomplete` must be absent because its whole failed state was quarantined.

```sh
sudo -u alfredmsg python3 -I - <<'PY'
import json
from pathlib import Path
state = Path('/var/lib/alfredmsg/hermes/installs/e1541360de565941')
fact = json.loads((state / 'facts.json').read_text())['packages']['venv']
environment = Path(fact['environment']).resolve()
assert environment.is_relative_to((state / 'environments').resolve())
assert (environment / 'pyvenv.cfg').is_file()
assert sorted(fact['extras']) == ['all', 'anthropic']
assert not (state / '.repair-incomplete').exists()
print('new-home PM selection and extras verified; paths suppressed')
PY
sudo sha256sum -c /var/backups/alfred-v1.1/original-dependencies.sha256
```

Finally, invoke the **exact pinned launcher** under `alfredmsg` with the proposed Hermes service filesystem and identity settings, while the old service still runs. `--run-module site` exits after Python startup and dependency activation; it does not launch Hermes gateway, Photon or Gateway intake. Require exit 0 and a new-home environment path in the reported `sys.path`. No PM repair message or dependency sync may occur during this probe. If it fails, do not cut over.

```sh
sudo systemd-run --unit=alfred-v11-launch-preflight --wait --collect --pipe \
  -p User=alfredmsg -p Group=alfredmsg -p SupplementaryGroups=alfredevidencero \
  -p RuntimeMaxSec=60 \
  -p WorkingDirectory=/var/lib/alfredmsg/hermes -p UMask=0077 \
  -p Environment=HERMES_HOME=/var/lib/alfredmsg/hermes \
  -p Environment=HERMES_RUNTIME_DIR=/var/lib/alfredmsg/hermes/tools \
  -p IPAddressDeny=any -p NoNewPrivileges=yes -p PrivateTmp=yes \
  -p ProtectHome=read-only -p ProtectSystem=strict \
  -p ReadWritePaths=/var/lib/alfredmsg \
  -p RestrictAddressFamilies='AF_UNIX AF_INET AF_INET6' \
  /home/alfred/.hermes/hermes-agent/.hermes/bin/hermes --run-module site
sudo sha256sum -c /var/backups/alfred-v1.1/original-dependencies.sha256
systemctl --user is-active hermes-gateway.service
```

The old service must still be `active`. Only after these checks pass may the approved migration procedure stop it. Repeat the launcher probe after the final Hermes-home sync and intake-plugin configuration, **before** enabling the new Hermes service; any new PM sync, repair or source write at that point is a stop-and-rollback condition. Keep the original Photon connection single throughout.

## Targeted rollback

Before cutover, a failed preflight requires no Personal Alfred restart: leave the old user service running, retain the failed new-home state and transient-unit journal for review, and restore only the ACLs changed above. Do not run PM repair against the original installation.

```sh
sudo setfacl --restore=/var/backups/alfred-v1.1/dependency-access.acl
systemctl --user is-active hermes-gateway.service
sudo sha256sum -c /var/backups/alfred-v1.1/original-dependencies.sha256
```

After a separately authorized cutover, follow `OPERATOR_MINIMAL_MIGRATION.md` section 4 first: stop new Hermes, Photon and intake services, verify port 8789 is free, restore the old unit and single Photon child. Then restore the saved ACLs. Retain new-home PM state for diagnosis; it is never installed into the old home. No Gateway authority or execution policy changes are involved.
