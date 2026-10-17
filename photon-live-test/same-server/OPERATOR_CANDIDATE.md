# Same-server test-only installation candidate — privileged trust boundary

**Human review and separate authorization required. Nothing in this document has been executed on the host.** The staging tree is writable by `alfred` and is never a root trust anchor. The only root-executed package code is an independently supplied, root-controlled `payload_gate.py` whose digest is checked against a separately protected approval record before use. The copied Node binary, JavaScript helpers and Photon SDK never run as root. No command enables the service or connects to Photon.

## Independent approval record

An independent reviewer must inspect the proposed payload archive, the gate source, the systemd/nft templates and this procedure. The reviewer records these three SHA-256 values **outside Task A staging** in `/root/photon-reply-test/approved.json`, owned by root with mode `0400`, under a root-only `0700` parent:

```json
{"payload_sha256":"<64 lowercase hex>","manifest_sha256":"<64 lowercase hex>","gate_sha256":"<64 lowercase hex>"}
```

The digest suggestions in `dist/PROPOSED_DIGESTS_v2.txt` are evidence for review, **not authority**. The approval record and reviewed gate at `/root/photon-reply-test/payload_gate.py` must be provisioned by an independently controlled root-only channel, never copied from writable staging by the installer. If the operator cannot establish this root-controlled handoff, **stop**. The gate's independently reviewed SHA-256 must match `gate_sha256` before any invocation. If the gate, archive or manifest changes after review, stop and obtain new approval. The `payload_sha256` covers the complete compressed package, including the manifest, Node binary, copied SDK, units and scripts. The separate manifest digest prevents a forged payload-internal manifest from becoming its own authority.

## 1. Root-private snapshot and pre-execution verification

After explicit authorization for test-only OS installation and separate root-controlled provisioning of the reviewed gate and approval record, run these in a root shell. The account, service and firewall remain untouched until the payload gate succeeds. The gate snapshots the one pinned staging archive through `O_NOFOLLOW|O_NONBLOCK`, rejects nonregular, linked and oversized inputs, and verifies the complete digest before publishing the private snapshot. It never reopens the writable source for extraction. An interrupted or mismatched handoff leaves no accepted snapshot. Inspect partial state before any retry.

```bash
set -euo pipefail
umask 077
staging=/home/alfred/alfred-development-lab/milestone2/task-a/photon-live-test
q=/srv/photon-reply-test/quarantine
approval=/root/photon-reply-test/approved.json
gate=/root/photon-reply-test/payload_gate.py
test -f "$approval" && test ! -L "$approval"
test -f "$gate" && test ! -L "$gate"
test "$(stat -c '%u:%g:%a:%h' "$approval")" = '0:0:400:1'
test "$(stat -c '%u:%g:%a:%h' "$gate")" = '0:0:400:1'
test "$(stat -c '%u:%g:%a' /root/photon-reply-test)" = '0:0:700'
acl_report=$(getfacl -cp /root/photon-reply-test "$approval" "$gate")
! printf '%s\n' "$acl_report" | /usr/bin/grep -E '^(default:|mask:|user:[^:]|group:[^:])'
test ! -e /srv/photon-reply-test && test ! -L /srv/photon-reply-test
test ! -e /etc/photon-reply-test
test ! -e /var/lib/photon-reply-test
test ! -e /etc/systemd/system/photon-reply-test@.service
test ! -e /etc/systemd/system/photon-reply-probe@.service
test ! -e /etc/systemd/system/photon-reply-control-initial@.service
test ! -e /etc/systemd/system/photon-reply-control-reconnect@.service
test ! -e /etc/systemd/system/photon-reply-results@.service
test ! -e /etc/systemd/system/photon-reply-test@.service.d
test ! -e /etc/systemd/system/photon-reply-probe@.service.d
! getent passwd photon-reply-test
approved_payload=$(/usr/bin/python3 -I -S -c 'import json,sys; print(json.load(open(sys.argv[1]))["payload_sha256"])' "$approval")
approved_gate=$(/usr/bin/python3 -I -S -c 'import json,sys; print(json.load(open(sys.argv[1]))["gate_sha256"])' "$approval")
test "$(/usr/bin/sha256sum "$gate" | /usr/bin/cut -d' ' -f1)" = "$approved_gate"
install -d -o root -g root -m 0700 /srv/photon-reply-test "$q"
/usr/bin/timeout --signal=TERM 180s /usr/bin/python3 -I -S "$gate" handoff \
  --source "$staging/dist/photon-reply-payload-v2.tar.gz" --destination "$q/payload.tar.gz" --approval "$approval"
test "$(stat -c '%u:%g:%a:%h' "$q/payload.tar.gz")" = '0:0:400:1'
acl_report=$(getfacl -cp "$q/payload.tar.gz")
! printf '%s\n' "$acl_report" | /usr/bin/grep -E '^(default:|mask:|user:[^:]|group:[^:])'
test "$(/usr/bin/sha256sum "$q/payload.tar.gz" | /usr/bin/cut -d' ' -f1)" = "$approved_payload"
/usr/bin/timeout --signal=TERM 180s /usr/bin/python3 -I -S "$gate" verify \
  --archive "$q/payload.tar.gz" --destination "$q/app" --approval "$approval"
test -f "$q/payload.ok" && test ! -L "$q/payload.ok"
test "$(cat "$q/payload.ok")" = "$approved_payload"
```

`payload_gate.py` rechecks its own SHA-256 and the archive against the root-protected approval record. It caps compressed bytes at 512 MiB, a regular entry at 256 MiB, aggregate entries at 700 MiB, manifest at 4 MiB and member count at 20,000; root execution also has CPU, address-space, file-size, file-descriptor and wall deadlines. It rejects traversal, duplicate/unlisted members, hard links, special files, unexpected execute bits, ACL metadata, escaped or dangling symlinks, modified files and a forged manifest. It extracts regular files before creating symlinks, writes only under the root-private quarantine, checks content hashes and sets root-owned read-only modes. It creates `payload.ok` **only after** full verification. A partial `app` directory without that marker is a failed install, never an acceptable runtime. The staging tree can change after the private snapshot without changing the pinned bytes.

## 2. Publish verified files, then create the test UID

Continue only if the preceding block exits successfully and the operator has reviewed the private copy. All files installed below come from the verified root-private extraction; no unit, NSS file or executable is read again from staging. Before service installation, run copied Node **only as the new unprivileged test UID inside a transient systemd chroot with no network or credentials** for integrity, ownership and import checks. The transient unit is a disposable installation check; it does not use the Photon service unit or connect to Photon. Its effective restrictions still need independent OS verification.

```bash
set -euo pipefail
q=/srv/photon-reply-test/quarantine
rootdir=/srv/photon-reply-test/root
test -f "$q/payload.ok" && test -d "$q/app" && test ! -L "$q/app"
install -d -o root -g root -m 0755 "$rootdir"
mv -T -- "$q/app" "$rootdir/app"
chmod 0755 /srv/photon-reply-test
install -d -o root -g root -m 0555 "$rootdir/usr" "$rootdir/etc" "$rootdir/etc/ssl" "$rootdir/etc/ssl/certs" "$rootdir/var" "$rootdir/var/lib" "$rootdir/var/lib/photon-reply-test" "$rootdir/run"
install -d -o root -g root -m 0555 "$rootdir/run/photon-reply-test-initial" "$rootdir/run/photon-reply-test-reconnect" "$rootdir/results"
install -d -o root -g root -m 1777 "$rootdir/tmp"
ln -s usr/lib "$rootdir/lib"
ln -s usr/lib64 "$rootdir/lib64"
install -o root -g root -m 0444 "$rootdir/app/same-server/chroot-nsswitch.conf" "$rootdir/etc/nsswitch.conf"
useradd --system --user-group --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin photon-reply-test
test_uid=$(id -u photon-reply-test)
test_gid=$(id -g photon-reply-test)
test "$test_uid" != "$(id -u alfred)"
test "$(id -Gn photon-reply-test)" = photon-reply-test
printf 'root:x:0:0:root:/root:/usr/sbin/nologin\nphoton-reply-test:x:%s:%s::/nonexistent:/usr/sbin/nologin\n' "$test_uid" "$test_gid" > "$rootdir/etc/passwd"
printf 'root:x:0:\nphoton-reply-test:x:%s:\n' "$test_gid" > "$rootdir/etc/group"
chmod 0444 "$rootdir/etc/passwd" "$rootdir/etc/group"
# The host systemd manager applies the chroot and drops privileges before ExecStart.
check_payload() {
  local check_name="$1"
  shift
  systemd-run --system --wait --collect --no-ask-password --expand-environment=no \
    --service-type=exec --unit="photon-payload-check-$check_name" \
    -p User=photon-reply-test -p Group=photon-reply-test \
    -p RootDirectory="$rootdir" -p WorkingDirectory=/app \
    -p 'BindReadOnlyPaths=/usr:/usr /etc/ssl/certs:/etc/ssl/certs' \
    -p PrivateNetwork=yes -p IPAddressDeny=any -p RestrictAddressFamilies=AF_UNIX \
    -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
    -p PrivateDevices=yes -p NoNewPrivileges=yes -p CapabilityBoundingSet= \
    -p AmbientCapabilities= -p RestrictNamespaces=yes -p SocketBindDeny=any \
    -p TasksMax=64 -p MemoryMax=512M -p StandardInput=null \
    /app/bin/node "$@"
}
check_payload integrity /app/scripts/integrity.mjs --verify
check_payload ownership /app/scripts/audit-runtime-copy.mjs /app
check_payload syntax --check /app/vendor/node_modules/@spectrum-ts/imessage/dist/index.js
check_payload import /app/src/runtime.mjs --dry-run
unset -f check_payload
install -d -o root -g root -m 0755 /srv/photon-reply-test/operator
install -d -o root -g root -m 0700 /etc/photon-reply-test
install -o root -g root -m 0644 "$rootdir/app/same-server/photon-reply-test@.service" /etc/systemd/system/photon-reply-test@.service
install -o root -g root -m 0644 "$rootdir/app/same-server/photon-reply-probe@.service" /etc/systemd/system/photon-reply-probe@.service
install -o root -g root -m 0644 "$rootdir/app/same-server/photon-reply-control-initial@.service" /etc/systemd/system/photon-reply-control-initial@.service
install -o root -g root -m 0644 "$rootdir/app/same-server/photon-reply-control-reconnect@.service" /etc/systemd/system/photon-reply-control-reconnect@.service
install -o root -g root -m 0644 "$rootdir/app/same-server/photon-reply-results@.service" /etc/systemd/system/photon-reply-results@.service
systemctl daemon-reload
```

The human operator creates a root-owned `0444` chroot `/etc/hosts` with only the separately reviewed provider hostnames and numeric addresses. Test-only `credentials.json` and `metadata.json` are later provisioned into `/etc/photon-reply-test` through a private root input channel, mode `0400`; never place secrets in staging, arguments, environment or logs. The OS acceptance marker remains absent until independent disposable tests pass. The unit retains `RootDirectory`, systemd credential copies, a dedicated UID, private runtime/state directories, cgroup IP deny and `SocketBindDeny=any`. Review `namei -l`, `getfacl -R`, `readelf -l`, `ldd`, effective unit properties and actual chroot mounts before any live use.

## 3. UID-specific nftables policy with host tools

No copied script runs as root here. The approved `render-network.mjs` runs as `photon-reply-test` in a transient systemd chroot with network disabled, reading a **nonsecret** root-owned `0444` `/srv/photon-reply-test/operator/network-policy.json` bind-mounted read-only at `/run/network-policy.json`. That JSON contains numeric `uid`, `ipv4` and `ipv6` arrays and must match `id -u photon-reply-test`. The root operator captures its bounded output, inspects the exact table/UID/address/port rules, then uses the installed host `/usr/sbin/nft` for syntax check and one atomic `-f` commit. The main test unit is stopped; there are no test UID processes during policy replacement.

```bash
set -euo pipefail
umask 077
app=/srv/photon-reply-test/root/app
test_uid=$(id -u photon-reply-test)
test -z "$(pgrep -u photon-reply-test || true)"
test ! -e /etc/photon-reply-test/network.nft
test ! -e /etc/photon-reply-test/network-installed.sha256
test -f /srv/photon-reply-test/operator/network-policy.json
test ! -L /srv/photon-reply-test/operator/network-policy.json
test "$(stat -c '%u:%g:%a:%h' /srv/photon-reply-test/operator/network-policy.json)" = '0:0:444:1'
nft list tables > /etc/photon-reply-test/tables.before
! rg -q '^table inet alfred_photon_reply_test$' /etc/photon-reply-test/tables.before
rendered=$(systemd-run --system --wait --collect --quiet --pipe --no-ask-password \
  --expand-environment=no --service-type=exec --unit=photon-payload-check-policy \
  -p User=photon-reply-test -p Group=photon-reply-test \
  -p RootDirectory=/srv/photon-reply-test/root -p WorkingDirectory=/app \
  -p 'BindReadOnlyPaths=/usr:/usr /etc/ssl/certs:/etc/ssl/certs /srv/photon-reply-test/operator/network-policy.json:/run/network-policy.json' \
  -p PrivateNetwork=yes -p IPAddressDeny=any -p RestrictAddressFamilies=AF_UNIX \
  -p ProtectSystem=strict -p ProtectHome=yes -p PrivateTmp=yes \
  -p PrivateDevices=yes -p NoNewPrivileges=yes -p CapabilityBoundingSet= \
  -p AmbientCapabilities= -p RestrictNamespaces=yes -p SocketBindDeny=any \
  -p TasksMax=64 -p MemoryMax=512M \
  /app/bin/node /app/scripts/render-network.mjs /run/network-policy.json "$test_uid")
printf '%s\n' "$rendered" > /etc/photon-reply-test/network.nft
chmod 0400 /etc/photon-reply-test/network.nft
nft -c -f /etc/photon-reply-test/network.nft
nft -f /etc/photon-reply-test/network.nft
nft -a list table inet alfred_photon_reply_test
/usr/bin/sha256sum /etc/photon-reply-test/network.nft > /etc/photon-reply-test/network-installed.sha256
chmod 0400 /etc/photon-reply-test/network-installed.sha256
```

The rendered batch begins with `create table inet alfred_photon_reply_test`; it fails if the table exists, matches only the test socket UID and never flushes or replaces another rule. `nft -f` commits the batch atomically. If interrupted between commit and marker creation, use read-only `nft -a list table inet alfred_photon_reply_test` and the targeted rollback below. A `SIGKILL` or power loss cannot be treated as a passed install. A changed policy requires stopped test processes, deletion of this table, a new reviewed JSON and a fresh syntax check. The old root-executed `firewall-transaction.mjs` CLI is removed; that module now contains only a pure failure-injection model for staging tests.

## 4. Disposable OS acceptance and live boundary

Use the separately reviewed `photon-reply-probe@.service` without Photon credentials to prove filesystem denial, credential separation, service-control denial, an AF_UNIX `0600` socket under `SocketBindDeny=any`, cgroup IP restrictions, nft UID drop behavior and stop/crash cleanup. Execute the **separate** cgroup-deny, nft-deny, approved-allow, local/private-deny and Personal Alfred unaffected trials in [NETWORK_ACCEPTANCE.md](NETWORK_ACCEPTANCE.md). The oneshot probe uses `TimeoutStartSec=15s`; no trial passes on a timeout or `ECONNREFUSED` alone. A positive trial requires a separately owned public TCP 443 listener and a temporary **probe-only** cgroup allow rule plus reviewed test UID nft rule. Remove that exception, restore provider-only policy and recheck denial before the main unit is eligible. The staging sandbox cannot perform these tests.

Only after separate OS review may a root operator create `/etc/photon-reply-test/os-acceptance.ok` (root `0400`). Missing marker, credentials, manifest or copied Node must cause a failed/prevented start. A successful `Type=exec` start proves only that the executable launched; inspect `systemctl show -p Result -p ActiveState -p MainPID`, the private control socket and bounded result file. Live Photon login, shared-line routing preflight and six live messages need **separate authorization**.

## 5. Targeted rollback and partial-state recovery

For a completed test-only installation, stop only the test units, check that the dedicated UID has no processes, validate the policy hash and delete only the uniquely named test table. Use host tools; never run copied Node or package scripts as root. Preserve redacted evidence and revoke test project credentials/routes through a separate human action.

```bash
set -euo pipefail
systemctl stop photon-reply-test@initial.service photon-reply-test@reconnect.service photon-reply-probe@local.service
test -z "$(pgrep -u photon-reply-test || true)"
test -f /etc/photon-reply-test/network-installed.sha256
/usr/bin/sha256sum -c /etc/photon-reply-test/network-installed.sha256
nft -a list table inet alfred_photon_reply_test
nft delete table inet alfred_photon_reply_test
nft list tables > /etc/photon-reply-test/tables.after
! rg -q '^table inet alfred_photon_reply_test$' /etc/photon-reply-test/tables.after
rm -f -- /etc/systemd/system/photon-reply-test@.service /etc/systemd/system/photon-reply-probe@.service /etc/systemd/system/photon-reply-control-initial@.service /etc/systemd/system/photon-reply-control-reconnect@.service /etc/systemd/system/photon-reply-results@.service
rm -rf -- /etc/systemd/system/photon-reply-test@.service.d /etc/systemd/system/photon-reply-probe@.service.d
systemctl daemon-reload
test -f /srv/photon-reply-test/quarantine/payload.ok
test ! -L /srv/photon-reply-test
rm -rf -- /srv/photon-reply-test /etc/photon-reply-test /var/lib/photon-reply-test
userdel photon-reply-test
```

If installation stopped **before** `payload.ok`, do not run `userdel`, `systemctl` or nft commands by habit: inspect `/srv/photon-reply-test/quarantine`, confirm no unit/account/table was created, and remove only the verified test quarantine after authorization. If the marker exists but `root/app`, account, unit or table is only partly present, inventory each with `stat`, `getent`, `systemctl status`, `pgrep -u` and `nft list table`; complete only the relevant targeted rollback steps. If the table or hash marker is absent, stop and independently review that state before deleting anything. Never flush the ruleset, delete an unreviewed table, reuse an existing test account, or remove a path another service uses.

The protected gate and approval record under `/root/photon-reply-test` remain for independent evidence retention. The reviewer may later revoke them through a separately authorized root-only action. They are not touched by automated rollback. The control/results units are never enabled and stop after each command. On an interrupted read or command, stop the observer only if the human test phase requires it; do not restart it automatically or repeat a possibly sent preview.

## Human review checklist

- Independently approve the gate source hash, complete payload archive hash and manifest hash; place the values and gate bytes through a root-controlled channel without copying staged digest suggestions or executing staging code as root.
- Inspect member inventory, safe path/link/type/mode rules, the complete systemd units, nft template and exact operator commands. Verify the approved archive contains the same files that will be installed.
- Confirm the root-protected gate hash **before** invoking it; inspect the bounded descriptor handoff and verify `payload.ok` appears only after complete extraction and verification.
- Confirm all later copied-Node actions run as `photon-reply-test`, with no credentials present during preflight; the root-only operations use distro tools and verified package files as data.
- Independently authorize and observe disposable OS isolation tests before creating the acceptance marker. Authorize Photon connection and messages separately.
