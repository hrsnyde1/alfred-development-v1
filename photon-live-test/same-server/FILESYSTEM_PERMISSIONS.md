# Test-only filesystem and permission manifest

This is the required **future** host layout for Ubuntu systemd 255. It has not been installed. All `/srv` and `/etc` paths below are outside this staging workspace and require separate human authorization. The staging tree is owned by `alfred` and is unsuitable as a service execution root.

| Host path | Owner/mode | Visible in service | Purpose |
|---|---|---|---|
| `/srv/photon-reply-test`, `/srv/photon-reply-test/root` | root:root `0755` | root of chroot | No write permission for `alfred` or service UID |
| `/srv/photon-reply-test/quarantine` | root:root `0700` | no | Root-private digest-approved archive snapshot, extracted files and `payload.ok` evidence; no staging-code execution |
| `/root/photon-reply-test/approved.json`, `payload_gate.py` | root:root `0400`, parent `0700` | no | Independently supplied approval and reviewed gate; neither copied by root from writable staging during installation |
| `/srv/photon-reply-test/root/app` and directories below | root:root `0555` | `/app` | Immutable reviewed runtime copy; no bind to staging |
| `/srv/photon-reply-test/root/app` regular data | root:root `0444`; `bin/node` `0555` | `/app` | SHA-256 manifest checked before every start; no hard links or external symlinks |
| `/srv/photon-reply-test/root/usr` | root:root `0555` | read-only bind of host `/usr` | Node interpreter, pinned system libraries and NSS modules only; never mount `/home`, `/etc`, `/run` or production trees |
| `/srv/photon-reply-test/root/lib`, `/lib64` | root-owned relative links to `usr/lib`, `usr/lib64` | same | Ubuntu 255 host uses this layout; compare with `readelf -l` and `ldd` on the copied Node before acceptance |
| `/srv/photon-reply-test/root/etc/ssl/certs` | mount target | read-only CA bind | TLS trust; review symlink resolution and host changes |
| `/srv/photon-reply-test/root/etc/hosts`, `nsswitch.conf` | root:root `0444` | yes | Fixed reviewed provider names/IPs; `hosts: files`; no resolver or host `/etc` bind |
| `/etc/photon-reply-test` | root:root `0700` | no | Root credential source and policy; never copy it into `/app` |
| `/etc/photon-reply-test/credentials.json`, `metadata.json` | root:root `0400` | only systemd `LoadCredential` copies under `/run/credentials/photon-reply-test@<phase>.service/` | Disposable test project only; no production secrets |
| `/etc/photon-reply-test/os-acceptance.ok` | root:root `0400` | no | Created **after** independent disposable OS tests, never as a shortcut |
| `/run/photon-reply-test-<phase>` | service UID/GID `0700` | `/run/...` | systemd `RuntimeDirectory`; AF_UNIX socket `0600`; removed when unit stops |
| `/var/lib/photon-reply-test/<phase>` | service UID/GID `0700` | `/var/lib/...` | systemd `StateDirectory`; bounded results persist for review |
| `/srv/photon-reply-test/root/run/photon-reply-test-{initial,reconnect}`, `/results` | root:root `0555` | mount targets only | Fixed targets for phase-specific control socket and read-only results binds; no broad host `/run` or state bind |
| `/etc/systemd/system/photon-reply-test@.service` | root:root `0644` | manager only | No `[Install]`, never enabled |
| `/etc/systemd/system/photon-reply-probe@.service` | root:root `0644` | manager only | Disposable listener checks; no Photon credentials or SDK activity |
| `/etc/systemd/system/photon-reply-control-{initial,reconnect}@.service` | root:root `0644` | manager only | Fixed command, chrooted test-UID operator controls; no credentials or IP access |
| `/etc/systemd/system/photon-reply-results@.service` | root:root `0644` | manager only | Unprivileged fixed-record reader with one read-only state bind |

`RootDirectory` changes the executable view. `ExecStartPre` and `ExecStart` therefore use `/app/bin/node`, which must exist under the root. The host `/usr` bind plus relative `/lib` and `/lib64` links satisfy the copied Node's ELF interpreter and `ldd` paths on this host; this must be retested after any OS or Node change. `MountAPIVFS=yes` gives a private `/run`. systemd 255 `RuntimeDirectory` and `StateDirectory` bind their host directories into a root-directory unit, and `LoadCredential` places per-unit copies under `$CREDENTIALS_DIRECTORY`. Their real ownership, path and access must be checked under the installed service UID; static inspection is insufficient.

The root operator verifies the separately provisioned gate and approval record before invoking the gate's bounded descriptor handoff. The gate snapshots only a regular, single-link source within size bounds, checks the approved digest, then checks archive members, paths, types, owners, modes, ACL metadata, symlinks, file hashes and the approved manifest before a runtime is published. Only then does `photon-reply-test` run copied Node for integrity, ownership, parse and import checks inside a transient `systemd-run` chroot with no network or credentials. The nft renderer uses the same confinement and a read-only bind of nonsecret policy. `ExecStartPre` repeats integrity checking inside the installed chroot as the service UID. No copied Node executable or staging JavaScript runs as root. The operator must also inspect POSIX ACLs (`getfacl -R`) on `/srv/photon-reply-test` and the copied tree: no ACL may grant `alfred` or the service UID write access. Check every parent with `namei -l`. Root ownership is not proved by the user-owned staging copy.

The unit uses `AssertPathExists` for the manifest, copied Node, two credential sources and OS acceptance marker. A missing input makes `systemctl start` fail rather than condition-skip. `ExecStartPre` validates the manifest and credential/project/path binding before the SDK can connect. The runtime binds its AF_UNIX control socket before `Spectrum(...)`; a socket failure therefore cannot happen after a Photon connection begins. `SocketBindDeny=any` is a cgroup IPv4/IPv6 bind filter in systemd 255, so it should permit AF_UNIX; the installed-unit socket test remains mandatory.
