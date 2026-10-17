# Publication approval refusal: staged diagnosis and conditional host repair

No host upgrade or publication operation has been run from this procedure.
The installed Developer release and Trusted Intake match the staged V1 files.

## Refusal condition

At 2026-10-16 07:09:18 UTC the existing Photon sidecar logged a `/send`
handler `ValidationError`: the chat passed to its SDK did not start with
`any;-;` (direct chat) or `any;+;` (group chat). The second owner DM identifier
is a canonical `any;-;+...` direct-chat GUID, as shown by the historical
development challenge receipt. The sidecar's `resolveSpace` converts that GUID
to a bare phone number, calls `space.create`, and uses the returned space for
`space.send`. The failing SDK call is `messages.sendText`, which requires the
full chat GUID. The sidecar returns HTTP 500; Intake's sender raises `OSError`,
Intake maps that to `publication_request_unavailable`, and the installed
`stage_publication.py` hides that code behind its generic RuntimeError.

The error reached Photon, so that request passed Intake's root peer check,
found its initialized `PublicationApprovalIssuer`, and passed the issuer's
publication plan validator. Intake runs as `alfred` and its evidence directory
is `alfred:alfred` mode `0700`, with a service `ReadWritePaths` allowance.
No `publication-*.json` evidence exists; the send failure happens before a
challenge receipt is written. Existing development grants are not consulted
by publication staging. The client validates the exact pinned plan locally
before it opens the socket; reaching `/send` also proves the issuer accepted
the bytes and schema. The live refusal code is inferred from the installed
exception mapping rather than captured directly from the socket.

## Minimal staged correction

[photon_dm_resolution.patch](photon_dm_resolution.patch) changes only the
sidecar's DM resolution branch. A canonical `any;-;+...` identifier is passed
to the existing `space.get` path intact. Bare E.164 phone inputs retain the
existing `space.create` path. This adds no connection, service, credential, or
authorization route. The patch has not been applied to the installed Photon
component. Its application would require separate authorization because the
current task requires Photon to remain unchanged.

Pinned source SHA-256: `d504559deb8fdde24b1804d3ede8b390a6d3c8154867a4e5a2c145cd90ba6ea1`.
Patch SHA-256: `e6e1eced34e59a1645b394f75fdaa2d5e6d79fdefa890c2f49f5ed9ff16690d0`.
Patched source SHA-256: `ef019d1d50e4ca680aede49276181f8eff8d396d9b7c22a73bb5da2b2d7bb8e4`.

The disposable test executes the original and patched `resolveSpace` with a
controlled SDK fixture. The original takes `create` for a canonical DM GUID;
the patch takes `get` and retains the GUID. It also checks bare-phone behavior
and JavaScript syntax. The publication fixture reproduces Intake's
`publication_request_unavailable` response when the existing sidecar send
fails, without creating approval evidence.

## Reviewed conditional host procedure (not authorized here)

Prepare and verify a disposable patched copy in the Development Lab:

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
PHOTON_SOURCE=/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/index.mjs
PATCH_STAGE=$(mktemp -d)
echo 'd504559deb8fdde24b1804d3ede8b390a6d3c8154867a4e5a2c145cd90ba6ea1  /home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/index.mjs' | sha256sum -c -
echo 'e6e1eced34e59a1645b394f75fdaa2d5e6d79fdefa890c2f49f5ed9ff16690d0  photon_dm_resolution.patch' | sha256sum -c -
cp "$PHOTON_SOURCE" "$PATCH_STAGE/index.mjs"
patch -d "$PATCH_STAGE" -p1 -i /home/alfred/alfred-development-lab/milestone2/task-a/photon_dm_resolution.patch
/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node --check "$PATCH_STAGE/index.mjs"
echo "ef019d1d50e4ca680aede49276181f8eff8d396d9b7c22a73bb5da2b2d7bb8e4  $PATCH_STAGE/index.mjs" | sha256sum -c -
```

Only after separate authorization, back up the pinned source and replace it.
The Developer activation marker, Developer package, Intake package, grant
records, QA evidence, Reviewer approval, publication plan, and authorization
directory are untouched. Only the existing Photon service needs a restart:

```bash
PHOTON_SOURCE=/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/index.mjs
PHOTON_BACKUP=/var/backups/alfred-photon-dm-resolution-v1
echo "d504559deb8fdde24b1804d3ede8b390a6d3c8154867a4e5a2c145cd90ba6ea1  $PHOTON_SOURCE" | sudo sha256sum -c -
sudo systemctl is-active --quiet alfred-photon.service alfred-development-intake.service alfred-hermes.service
sudo test ! -e "$PHOTON_BACKUP"
sudo test ! -e "$PHOTON_SOURCE.next"
sudo install -d -m 0700 -o root -g root "$PHOTON_BACKUP"
sudo cp -a "$PHOTON_SOURCE" "$PHOTON_BACKUP/index.mjs"
echo "d504559deb8fdde24b1804d3ede8b390a6d3c8154867a4e5a2c145cd90ba6ea1  $PHOTON_BACKUP/index.mjs" | sudo sha256sum -c -
sudo install -m 0644 "$PATCH_STAGE/index.mjs" "$PHOTON_SOURCE.next"
echo "ef019d1d50e4ca680aede49276181f8eff8d396d9b7c22a73bb5da2b2d7bb8e4  $PHOTON_SOURCE.next" | sudo sha256sum -c -
sudo mv -T "$PHOTON_SOURCE.next" "$PHOTON_SOURCE"
sudo systemctl restart alfred-photon.service
sudo systemctl is-active --quiet alfred-photon.service alfred-development-intake.service alfred-hermes.service
echo "ef019d1d50e4ca680aede49276181f8eff8d396d9b7c22a73bb5da2b2d7bb8e4  $PHOTON_SOURCE" | sudo sha256sum -c -
```

If any command after replacement fails, stop and roll back the Photon file;
do not attempt publication staging. The reviewed rollback is:

```bash
PHOTON_SOURCE=/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/index.mjs
PHOTON_BACKUP=/var/backups/alfred-photon-dm-resolution-v1
echo "d504559deb8fdde24b1804d3ede8b390a6d3c8154867a4e5a2c145cd90ba6ea1  $PHOTON_BACKUP/index.mjs" | sudo sha256sum -c -
sudo install -m 0644 "$PHOTON_BACKUP/index.mjs" "$PHOTON_SOURCE.next"
sudo mv -T "$PHOTON_SOURCE.next" "$PHOTON_SOURCE"
sudo systemctl restart alfred-photon.service
sudo systemctl is-active --quiet alfred-photon.service alfred-development-intake.service alfred-hermes.service
echo "d504559deb8fdde24b1804d3ede8b390a6d3c8154867a4e5a2c145cd90ba6ea1  $PHOTON_SOURCE" | sudo sha256sum -c -
```
