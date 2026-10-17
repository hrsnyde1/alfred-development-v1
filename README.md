# Alfred Development V1

Public source snapshot of the Alfred Development V1 Development Lab.

## Intended workflow

Owner iMessage → Personal Alfred (Hermes) → Trusted Intake → Gateway → Central CTO
plan → native owner development approval → specialist Developer → Independent QA
→ Independent Reviewer → separate native owner publication approval → GitHub draft
PR → verified completion notification. Merging and deployment remain separate owner
actions.

## Current status

This upload does not install or activate production software. The development-handoff
correction is staged and tested; deployment is currently held in Phase A by the
unchanged Photon dependency ownership contract and required root authentication.
See [deployment status](development_challenge/DEPLOYMENT_STATUS.md). Historical
acceptance success does not establish readiness of the current fresh-task flow.

## Components

- `fresh_v1/`: existing pipeline handoffs and protected host integration.
- `developer_v1/`: development approval, specialist routing and execution.
- `independent_qa/`, `independent_reviewer/`: independent validation stages.
- `draft_pr_publisher/`: separately authorized draft PR publication.
- `completion_integration/`: verified completion and durable delivery tracking.
- `v1_cto/`, `v1_1a/`, `v1_1b/`, `v1_1_activation/`, `task_a/`: integration sources
  and historical staging work.
- `development_challenge/`: functional correction, tests and reviewed host procedure.
- `tests/`, `templates/`, `photon-live-test/`: tests, configuration examples and
  isolated Photon integration sources.
- `dist/`: original release archives, manifests and staged release trees.

## Installation and tests

Start with [the reviewed handoff host procedure](development_challenge/HOST.md),
[its report](development_challenge/REPORT.md), and
[focused test instructions](development_challenge/TESTS.md). Production installation,
service activation and live acceptance remain separately authorized operations.
Some host integration tests require the original Linux installation, protected
evidence or locally installed dependencies; this source snapshot is not a portable
production installer or a claim that every test runs on a clean machine.

## Public export

See [PUBLIC_EXPORT.md](PUBLIC_EXPORT.md) for export boundaries and the checksum
inventory. The original staging overview is retained in
[docs/history/TASK_A_STAGING_README.md](docs/history/TASK_A_STAGING_README.md).
