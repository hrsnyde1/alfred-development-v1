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

# 3b. handoff.3: Evidence sandbox write paths, recorded-failure skip, two-file installer.
run handoff3 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_evidence_sandbox_paths.py \
  tests/test_development_handoff3_upgrade.py tests/test_development_challenge_delivery.py \
  --junitxml="$OUT/handoff3.xml"

# 3c. handoff.4: writable lab repository, recorded pre-dispatch host failures, the
#     one T-0005 QA recovery, and the four-file installer.
run handoff4 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_fresh_v1_qa_recovery.py \
  tests/test_development_handoff4_upgrade.py tests/test_evidence_sandbox_paths.py \
  --junitxml="$OUT/handoff4.xml"

# 3d. handoff.5: role identities observe PAUSE/STOP through the sandbox's read-only
#     gateway view and still fail closed; the two-file installer.
run handoff5 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_fresh_v1_role_gateway_view.py \
  tests/test_development_handoff5_upgrade.py --junitxml="$OUT/handoff5.xml"

# 3e. handoff.6: Developer and Reviewer accept Codex progress notes before exactly one
#     final contract-shaped message; the four-file installer with inventory checks.
run handoff6 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_model_message_contract.py \
  tests/test_development_handoff6_upgrade.py --junitxml="$OUT/handoff6.xml"

# 3f. handoff.7: root's snapshot clone trusts the worktree, its git directory and the
#     registered common directory (git ownership hardening); the one-file installer.
run handoff7 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_root_clone_ownership.py \
  tests/test_development_handoff7_upgrade.py --junitxml="$OUT/handoff7.xml"

# handoff.8: owner-delegated development approval, its installer, Independent QA's
# evidence check and the restricted root operations helper.
run handoff8 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_delegated_development_approval.py \
  tests/test_development_handoff8_upgrade.py tests/test_alfred_dev_ops.py tests/test_independent_qa.py \
  tests/test_developer_execution_v1.py --junitxml="$OUT/handoff8.xml"

# handoff.9: the intake files the owner's request when Hermes submits a clarifying answer.
run handoff9 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_intake_clarifying_answer.py \
  tests/test_development_handoff9_upgrade.py --junitxml="$OUT/handoff9.xml"

# handoff.10: informational Reviewer findings advance; everything else still holds.
run handoff10 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_reviewer_info_findings.py \
  tests/test_development_handoff10_upgrade.py --junitxml="$OUT/handoff10.xml"

# handoff.11: plain-language owner texts, "yes" approvals and owner-run resend.
run handoff11 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_plain_language_approvals.py \
  tests/test_development_handoff11_upgrade.py tests/test_completion_integration.py \
  --junitxml="$OUT/handoff11.xml"

# handoff.12: multi-project policy, staffing, natural project names, non-blocking poll.
run handoff12 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_multi_project.py \
  tests/test_development_handoff12_upgrade.py --junitxml="$OUT/handoff12.xml"

# 4. Central CTO.
run central-cto env PYTHONPATH="$LAB:/home/alfred/Git/alfred/.dev/bin:/home/alfred/Git/alfred/src" \
  "$PYTHON" -B -m pytest -q -p no:cacheprovider v1_cto/tests --junitxml="$OUT/central-cto.xml"

# 5. This bundle's own read-only tools: Phase D evidence and Gate 7 snapshots, and
#    the Gate 5 post-restart check.
run evidence-capture "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_capture_evidence.py \
  tests/test_post_restart_check.py --junitxml="$OUT/evidence-capture.xml"

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
