#!/bin/bash
# Evidence gate 1: the full offline test evidence on the Linux host, as alfred (not root).
# Runs only tests: no installation, service action, Photon send, model call or GitHub
# write. Tests use disposable fixtures, mocked models/GitHub and local Git repositories.
# Writes only verification/results/<UTC timestamp>/ inside this checkout.
set -euo pipefail

if test "$(id -u)" = 0; then
  echo 'Stop: run as alfred, not root. The tests never need privileges.' >&2
  exit 2
fi

LAB=$(cd "$(dirname "$0")/.." && pwd)
PYTHON=/home/alfred/Git/alfred/.venv/bin/python
NODE=/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node
OUT="$LAB/verification/results/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT"
cd "$LAB"

status=0
run() {
  local name=$1; shift
  echo "== $name"
  if "$@" >"$OUT/$name.log" 2>&1; then
    echo "   PASS  ($(tail -1 "$OUT/$name.log"))"
  else
    echo "   FAIL  (see $OUT/$name.log)"
    status=1
  fi
}

# 1. The reviewed handoff selection, now including the handoff.2 owner-contract tests.
mapfile -t SELECTION < development_challenge/test-selection.txt
run handoff-selection "$PYTHON" -B -m pytest -q -p no:cacheprovider "${SELECTION[@]}" \
  --junitxml="$OUT/handoff-selection.xml"

# 2. The whole chain: native request -> CTO -> Developer -> QA -> Reviewer -> draft PR
#    -> completion, with model and GitHub test doubles. Every test in the file.
run fresh-v1-end-to-end "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_fresh_v1.py \
  --junitxml="$OUT/fresh-v1-end-to-end.xml"

# 3. Phase A continuation and the corrected installer transaction (Linux /tmp roots).
run phase-a-and-installer "$PYTHON" -B -m pytest -q -p no:cacheprovider \
  tests/test_phase_a_continuation.py tests/test_development_handoff_upgrade.py \
  tests/test_handoff_dependency_owner_contract.py --junitxml="$OUT/phase-a-and-installer.xml"

# 4. Central CTO.
run central-cto env PYTHONPATH="$LAB:/home/alfred/Git/alfred/.dev/bin:/home/alfred/Git/alfred/src" \
  "$PYTHON" -B -m pytest -q -p no:cacheprovider v1_cto/tests --junitxml="$OUT/central-cto.xml"

# 5. Evidence capture script (this bundle's own read-only tool).
run evidence-capture "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_capture_evidence.py \
  --junitxml="$OUT/evidence-capture.xml"

# 6. Photon development observer (in-process, no socket or SDK connection).
run node-observer "$NODE" --test --test-reporter=tap --experimental-test-isolation=none \
  development_challenge/tests/development-observe.test.mjs

# Pin what was tested, so results tie to exact source bytes.
git -C "$LAB" rev-parse HEAD >"$OUT/source-revision.txt" 2>/dev/null || true
sha256sum development_challenge/install_patch.py development_challenge/phase_a_continue.py \
  development_challenge/PHASE_A_PREPARE.sh dist/alfred-fresh-v1-1.0.1-development-handoff.2.tar.gz \
  >"$OUT/tested-sha256.txt"

echo
if test "$status" = 0; then
  echo "GATE 1 PASS: all suites passed. Results: $OUT"
else
  echo "GATE 1 FAIL: do not proceed to Phase A. Results: $OUT"
fi
exit "$status"
