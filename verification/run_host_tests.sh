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

# handoff.14: a task held by a recorded verdict no longer blocks later requests.
run handoff14 "$PYTHON" -B -m pytest -q -p no:cacheprovider \
  tests/test_development_handoff14_upgrade.py --junitxml="$OUT/handoff14.xml"

# handoff.16: team skills (handoff.13 rebuilt with the Gateway owner rule).
run handoff16 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_team_skills.py \
  tests/test_development_handoff16_upgrade.py --junitxml="$OUT/handoff16.xml"

# handoff.17: the team fixes its own work (handoff.15 repackaged without Gateway pins).
run handoff17 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_fix_loop.py \
  tests/test_development_handoff15_upgrade.py tests/test_development_handoff17_upgrade.py \
  tests/test_independent_qa.py --junitxml="$OUT/handoff17.xml"

# handoff.18: the demo site's lab repository is writable in the Evidence sandbox.
run handoff18 "$PYTHON" -B -m pytest -q -p no:cacheprovider \
  tests/test_development_handoff18_upgrade.py --junitxml="$OUT/handoff18.xml"

# handoff.19: plain requests pass QA's plan check; QA verdicts are recorded; abandon.
run handoff19 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_plain_requests_reach_qa.py \
  tests/test_development_handoff19_upgrade.py tests/test_alfred_dev_ops.py \
  --junitxml="$OUT/handoff19.xml"

# handoff.20: the owner can retry a publish that reported a definite error.
run handoff20 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_publish_retry.py \
  tests/test_development_handoff20_upgrade.py --junitxml="$OUT/handoff20.xml"

# handoff.21: the agents run on Claude with their reviewed identities (Phase 1).
run handoff21 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_claude_agents.py \
  tests/test_development_handoff21_upgrade.py tests/test_developer_execution_v1.py \
  tests/test_team_skills.py tests/test_model_message_contract.py tests/test_fix_loop.py \
  --junitxml="$OUT/handoff21.xml"

# handoff.22: handoff.20 repackaged to install after handoff.21.
run handoff22 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_publish_retry.py \
  tests/test_development_handoff22_upgrade.py --junitxml="$OUT/handoff22.xml"

# handoff.23: a slow Photon acknowledgement no longer fails a delivered completion.
run handoff23 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_completion_ack_timeout.py \
  tests/test_completion_integration.py tests/test_completion_reconciliation.py \
  tests/test_development_handoff23_upgrade.py --junitxml="$OUT/handoff23.xml"

# handoff.26: the agents use their own Claude token; login errors fall back to Codex.
run handoff26 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_claude_agents.py \
  tests/test_development_handoff26_upgrade.py tests/test_alfred_dev_ops.py \
  --junitxml="$OUT/handoff26.xml"

# handoff.24: the owner confirms a completion text whose delivery record stayed uncertain.
run handoff24 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_confirm_delivered.py \
  tests/test_publish_retry.py tests/test_development_handoff24_upgrade.py \
  --junitxml="$OUT/handoff24.xml"

# handoff.27: the pipeline speaks in the squads' Telegram chats.
run handoff27 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_dev_squads.py \
  tests/test_development_handoff27_upgrade.py --junitxml="$OUT/handoff27.xml"

# handoff.28: the squads announcer reads real developer reports.
run handoff28 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_dev_squads.py \
  tests/test_development_handoff28_upgrade.py --junitxml="$OUT/handoff28.xml"

# handoff.29: one yes takes a request to a draft PR; requests in the owner's own words.
run handoff29 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_one_yes_flow.py \
  tests/test_development_handoff29_upgrade.py tests/test_completion_integration.py tests/test_dev_squads.py --junitxml="$OUT/handoff29.xml"

# handoff.30: QA accepts delegated draft-PR policy.
run handoff30 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_delegated_development_approval.py \
  tests/test_independent_qa.py tests/test_development_handoff30_upgrade.py --junitxml="$OUT/handoff30.xml"

# handoff.31: automatic squash merge after QA and review, and the owner's "undo".
run handoff31 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_auto_merge_undo.py \
  tests/test_development_handoff31_upgrade.py tests/test_delegated_development_approval.py \
  tests/test_one_yes_flow.py tests/test_completion_integration.py tests/test_dev_squads.py \
  --junitxml="$OUT/handoff31.xml"

# handoff.33: the owner's one approval is the CTO plan text; listed requests file directly.
run handoff33 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_plan_approval_flow.py \
  tests/test_development_handoff33_upgrade.py tests/test_one_yes_flow.py \
  tests/test_auto_merge_undo.py tests/test_delegated_development_approval.py \
  tests/test_independent_qa.py tests/test_dev_squads.py --junitxml="$OUT/handoff33.xml"

# handoff.34: Repo Intelligence; the CTO plan and the specialists know the repositories.
run handoff34 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_repo_intelligence.py \
  tests/test_development_handoff34_upgrade.py tests/test_team_snapshot.py tests/test_team_skills.py \
  tests/test_claude_agents.py tests/test_fix_loop.py --junitxml="$OUT/handoff34.xml"

# handoff.35: agent identities may include Escalation.md.
run handoff35 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_claude_agents.py tests/test_team_snapshot.py \
  tests/test_development_handoff35_upgrade.py --junitxml="$OUT/handoff35.xml"

# handoff.36: the reviewed workforce identities, with the shared charter, reach the agents.
run handoff36 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_claude_agents.py tests/test_team_snapshot.py \
  tests/test_repo_intelligence.py tests/test_fresh_v1.py tests/test_development_handoff36_upgrade.py \
  --junitxml="$OUT/handoff36.xml"

# handoff.37: plain-language requests are staffed from the files the work touches.
run handoff37 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_staffing.py tests/test_fresh_v1.py \
  tests/test_development_handoff37_upgrade.py --junitxml="$OUT/handoff37.xml"

# handoff.39: the plan's recorded staffing is what approval and dispatch route by.
run handoff39 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_staffing.py tests/test_fresh_v1.py \
  tests/test_developer_v1.py tests/test_development_handoff39_upgrade.py --junitxml="$OUT/handoff39.xml"

# handoff.40: planning waits for the Gateway lock instead of holding the task.
run handoff40 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_fresh_v1.py tests/test_staffing.py \
  tests/test_development_handoff40_upgrade.py --junitxml="$OUT/handoff40.xml"

# handoff.41: only code-checkable criteria go on the QA and Review checklist.
run handoff41 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_criteria_triage.py tests/test_fresh_v1.py \
  tests/test_development_handoff41_upgrade.py --junitxml="$OUT/handoff41.xml"

# handoff.38: a refused plan step texts the owner once, with a fixed reason.
run handoff38 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_plan_refusal_notice.py \
  tests/test_fix_loop.py tests/test_fresh_v1.py tests/test_development_handoff38_upgrade.py \
  --junitxml="$OUT/handoff38.xml"

# handoff.42: handoff.38's refusal texts, re-pinned to install after handoff.41.
run handoff42 "$PYTHON" -B -m pytest -q -p no:cacheprovider tests/test_plan_refusal_notice.py \
  tests/test_fresh_v1.py tests/test_development_handoff42_upgrade.py --junitxml="$OUT/handoff42.xml"

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
