#!/usr/bin/env bash
# Offline host check; no credentials and no Photon connection.
set -euo pipefail
runtime_root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
bwrap --die-with-parent --unshare-all --share-net --clearenv \
  --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64 \
  --dir /etc --dir /etc/ssl --ro-bind /etc/ssl/certs /etc/ssl/certs \
  --ro-bind /etc/resolv.conf /etc/resolv.conf --ro-bind /etc/hosts /etc/hosts \
  --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run \
  --ro-bind "$runtime_root" /app \
  --setenv HOME /tmp --setenv PHOTON_TEST_ISOLATED 1 \
  /app/bin/node /app/src/isolation-probe.mjs
