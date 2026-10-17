#!/usr/bin/env bash
# Read-only inventory; does not read secrets, contact Photon or touch services.
set -euo pipefail
runtime_root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
"$runtime_root/bin/node" "$runtime_root/scripts/integrity.mjs" --verify
systemd --version | head -1
findmnt -n -o FSTYPE,OPTIONS /sys/fs/cgroup
if getent passwd photon-reply-test >/dev/null; then
  echo "Dedicated test identity exists; inspect groups and ownership before installation."
else
  echo "Dedicated test identity absent; creation requires separate authorization."
fi
for protected in /home/alfred/.hermes /home/alfred/alfred-development-lab; do
  if [[ -e "$protected" ]]; then stat -c '%A %a %U:%G %n' -- "$protected"; fi
done
if command -v nft >/dev/null; then command -v nft; else echo "nft unavailable"; fi
systemd-analyze security --offline=yes --no-pager "$runtime_root/same-server/photon-reply-test@.service" | tail -1
"$runtime_root/bin/node" "$runtime_root/scripts/verify-unit.mjs"
"$runtime_root/bin/node" "$runtime_root/scripts/check-chroot-layout.mjs"
