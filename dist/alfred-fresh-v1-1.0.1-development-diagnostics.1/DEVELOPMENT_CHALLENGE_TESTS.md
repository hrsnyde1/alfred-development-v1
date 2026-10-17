# Development challenge staging verification

2026-10-16: **353 passed, 58 subtests passed, 2 skipped** (40.92 seconds).
JUnit evidence: `development-challenge-staging-tests.xml`.
The skipped tests are explicitly opt-in authenticated live-model probes.

New focused files: **22 passed**, comprising 13 diagnostic/transport tests and
9 disposable installation/rollback tests. Includes three deterministic original
Intake reproductions in which delivery occurs before the generic refusal.

Run from the Development Lab with the existing staging dependencies and pinned
historical releases (the overlay does not duplicate those dependencies):

```bash
/home/alfred/Git/alfred/.venv/bin/python -m pytest -q \
  tests/test_development_challenge_failure.py tests/test_development_diagnostics_upgrade.py \
  tests/test_fresh_v1_recovery.py tests/test_fresh_v1_planning_failure.py \
  tests/test_fresh_v1.py tests/test_fresh_v1_release.py \
  tests/test_developer_v1.py tests/test_developer_execution_v1.py \
  tests/test_gateway_adapter_v1.py tests/test_host_install_v1.py \
  tests/test_approval_evidence_host_v1.py tests/test_publication_approval.py \
  tests/test_publication_host_transaction.py tests/test_independent_qa.py \
  tests/test_independent_reviewer.py tests/test_draft_pr_publisher.py \
  tests/test_draft_pr_release.py tests/test_completion_integration.py \
  tests/test_completion_delivery.py tests/test_completion_reconciliation.py \
  v1_cto/tests/test_cto.py --junitxml=development-challenge-staging-tests.xml
```

The real V1 code and sandboxed local checks operate only on disposable fixture
repositories, mocked Photon/model/GitHub calls and mock owner events. No live
issuer, production workflow, GitHub write or protected state is exercised.

First broad run: 349 passed, 4 failed, 2 skipped, 58 subtests passed. All four
failures were in the historical planning-recovery installer fixture, which read
its expected pre-upgrade bytes from the now-upgraded live installation. That
fixture now copies pinned historical staging release bytes and asserts their
hashes. The recovery runtime and old release artifacts were not changed. Final
full rerun above passed.

Full configured lint passes for the new tests and patch transaction. F/E9 lint
passes for the modified Intake. Existing unrelated Intake style findings were
not rewritten. Only one runtime source file differs from the installed Developer
inventory; the corresponding inventory digest is updated.
