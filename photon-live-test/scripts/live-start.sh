#!/usr/bin/env bash
# Human-operated only, after separate live authorization. Never run for dry-run.
set -euo pipefail
runtime_root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
# With --share-net, a host that contains Personal Alfred is not an isolated
# test host. Require a disposable host/VM with an independently reviewed egress
# boundary before accepting credentials or creating result files.
if [[ -e /home/alfred/.hermes || "${PHOTON_TEST_NETWORK_BOUNDARY_CONFIRMED:-}" != 1 ]]; then
  echo "Disposable host and independently confirmed network boundary required." >&2; exit 2
fi
: "${PHOTON_TEST_CREDENTIAL_FILE:?set path to private test-only credentials JSON}"
: "${PHOTON_TEST_METADATA_FILE:?set path to private routing metadata JSON}"
: "${PHOTON_TEST_RESULTS_DIR:?set path to a new private result directory}"
: "${XDG_RUNTIME_DIR:?owner-only XDG_RUNTIME_DIR required for private inputs and results}"
if [[ ! -d "$XDG_RUNTIME_DIR" || ! -O "$XDG_RUNTIME_DIR" || "$(stat -c %a -- "$XDG_RUNTIME_DIR")" != 700 ]]; then
  echo "Private runtime parent must be owner-owned, mode 0700." >&2; exit 2
fi
private_root=$(realpath -e -- "$XDG_RUNTIME_DIR")
for candidate in "$PHOTON_TEST_CREDENTIAL_FILE" "$PHOTON_TEST_METADATA_FILE" "$PHOTON_TEST_RESULTS_DIR"; do
  if [[ "$(realpath -m -- "$candidate")" != "$private_root/"* ]]; then
    echo "All private paths must be inside XDG_RUNTIME_DIR." >&2; exit 2
  fi
done
phase=${PHOTON_TEST_PHASE:-initial}
if [[ "$phase" != initial && "$phase" != reconnect ]]; then exit 2; fi
if [[ -e "$PHOTON_TEST_RESULTS_DIR" || -L "$PHOTON_TEST_RESULTS_DIR" ]]; then
  echo "Result directory must be new." >&2; exit 2
fi
for file in "$PHOTON_TEST_CREDENTIAL_FILE" "$PHOTON_TEST_METADATA_FILE"; do
  if [[ ! -f "$file" || -L "$file" || ! -O "$file" || "$(stat -c %a -- "$file")" != 600 ]]; then
    echo "Private input must be owner-owned regular file, mode 0600." >&2; exit 2
  fi
done
if ! command -v bwrap >/dev/null; then echo "bubblewrap required." >&2; exit 2; fi
"$runtime_root/bin/node" "$runtime_root/scripts/integrity.mjs" --verify
mkdir -m 700 -- "$PHOTON_TEST_RESULTS_DIR"
if [[ "$(stat -c %a -- "$PHOTON_TEST_RESULTS_DIR")" != 700 ]]; then exit 2; fi
# No host home, Hermes, Gateway, repository parent, or ambient environment is mounted.
# SDK stdout/stderr are discarded; only fixed, privacy-safe control/results files persist.
bwrap --die-with-parent --unshare-all --share-net --clearenv \
  --ro-bind /usr /usr --ro-bind /lib /lib --ro-bind /lib64 /lib64 \
  --dir /etc --dir /etc/ssl --ro-bind /etc/ssl/certs /etc/ssl/certs \
  --ro-bind /etc/resolv.conf /etc/resolv.conf --ro-bind /etc/hosts /etc/hosts \
  --proc /proc --dev /dev --tmpfs /tmp --tmpfs /run \
  --ro-bind "$runtime_root" /app \
  --ro-bind "$PHOTON_TEST_CREDENTIAL_FILE" /run/credentials.json \
  --ro-bind "$PHOTON_TEST_METADATA_FILE" /run/metadata.json \
  --bind "$PHOTON_TEST_RESULTS_DIR" /run/results \
  --setenv HOME /tmp --setenv PHOTON_TEST_ISOLATED 1 \
  --setenv PHOTON_TEST_PHASE "$phase" \
  /app/bin/node /app/src/runtime.mjs --live 1>/dev/null 2>/dev/null
echo "Isolated session ended. Review private control.txt and results.ndjson." >&2
