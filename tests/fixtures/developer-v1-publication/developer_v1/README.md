# Alfred Development V1 — Developer execution staging

The eleven specialist definitions, CTO router, shared assignment schemas and
coordination logic remain in this package. This milestone adds a protected
development grant path, one reusable real worker, an on-demand Gateway entry
point and a disposable real-model acceptance test. Nothing in this staging
tree is installed or active on the host.

## Trust path

1. `gateway_adapter.read_gateway_inputs` reads the registered repository,
   uniquely filed canonical task and exact CTO plan through the existing
   Gateway parser, registry, journal and plan schema. A plan requiring
   clarification is refused.
2. The installed trusted Intake source already matches the staged
   `trusted_intake_development.py` byte for byte. No source replacement is
   needed. Its administrator-only operation recomputes the
   approval request from those Gateway artifacts and sends one challenge with
   the existing Photon control sender. It does not change Photon or Gateway
   task filing. The existing Photon observer socket carries the SDK's
   `nativeReplyTargetGuid`; the Intake gate alone accepts that observation
   from the sidecar UID. The grant issuer requires an exact direct threaded
   owner reply, same DM, no forward, matching plan phrase and five-minute
   challenge age. It stores an expiring grant in a mode `0700` directory.
3. `ProtectedDevelopmentAuthority` reads only a protected, matching grant.
   The grant binds project/task, raw spec and plan SHA-256, repository,
   worktree root, file scope and specialties. It permits local development
   edits, checks and an authorized local commit; it never permits merge,
   deployment or GitHub publication. Fixture grants carry a `staging`
   environment marker; the host entry point requires `host`, so a copied
   fixture grant cannot authorize a live task. Gateway task
   approval, a conversation or CTO plan delivery does not satisfy this check.
4. `pipeline.execute_gateway_task` and `run_task.py` route only after grant
   verification. The host request supplies bounded, nonoverlapping CTO work
   items; dependencies run in order. Independent work uses separate worktrees.
   The final QA branch cherry-picks inspected developer commits so QA receives
   one coherent change set. Duplicate assignment IDs cannot start twice.
5. `real_worker.py` uses one authenticated Codex broker for every specialist.
   The selected provider/model and reasoning effort come from the protected
   model config. A task override can choose only a configured primary or
   fallback. The broker runs read-only with shell, browser, app and code tools
   disabled. It receives only assigned source text and returns a constrained
   JSON edit plan. An OS-isolated bubblewrap applier writes only assigned
   worktree paths. Checks run in bubblewrap with a read-only worktree, no
   network and no provider credentials. The host verifier also requires a
   root-owned activation marker; rollback removes it before restoring config.
   File hashes, check outcomes, commits and the actual model used appear in
   the Developer report. A completed report produces `alfred.qa-input/1`; QA
   itself remains a separate future stage.

The generic model contract can name other providers. This staged execution
backend accepts only the authenticated Codex provider; an unsupported or
unauthenticated route fails closed. `models.codex-verified.example.json` is a
reviewable configuration, not a hardcoded model selection in worker code.
The two example model routes were invoked successfully during staged tests on
2026-10-15. Model cost fields are operator planning units, not live billing
telemetry.

## Reviewed foundations

- Gateway CTO and plan schema: `/home/alfred/Git/alfred/.dev/bin/cto.py` and
  `plan.schema.json`.
- Gateway registry, task parser, journal and existing spec approval records.
  The existing approval record does not bind a CTO plan or development scope.
- Installed Photon sidecar's observer and native reply target fields, plus the
  installed trusted Intake gate and its protected Unix socket peer checks.
- Existing lab execution candidates. They are tied to a calculator path and
  fixed project, so this worker reuses their bubblewrap pattern, not their
  hardcoded authorization.
- Installed Codex CLI and authentication; Hermes development profiles and
  auxiliary model routing were inspected. No Personal Alfred model or auth
  configuration was changed.

## Tests and installation

Run all staged Developer tests, including the explicit disposable real-model
case, with bubblewrap-capable host permissions:

```bash
ALFRED_REAL_MODEL_ACCEPTANCE=1 /home/alfred/Git/alfred/.venv/bin/python -m unittest tests/test_developer_v1.py tests/test_gateway_adapter_v1.py tests/test_developer_execution_v1.py -v
```

See [HOST_ACCEPTANCE.md](HOST_ACCEPTANCE.md) for the reviewed administrator
installation, native-reply live acceptance and targeted rollback. Do not run
the live approval challenge or a real task without separate owner approval.
T-0001 remains unapproved and unexecuted because its website repository is
not identified.
