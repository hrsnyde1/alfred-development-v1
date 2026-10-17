# Task A security-contract investigation: focused test record

Date: 2026-10-14. Scope: staging files and installed source read-only. No
release archive, upstream patch, live Photon intake, Gateway dispatcher,
protected state, service operation or production file was changed.

## Reproduction

From `/home/alfred/alfred-development-lab/milestone2/task-a`:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 TMPDIR=/tmp PYTHONPATH=/home/alfred/.cache/uv/archive-v0/DK4n9G7xyVKZZ3KJ:/home/alfred/.cache/uv/archive-v0/Vd_UqZgwiCKPnjqT:/home/alfred/.cache/uv/archive-v0/yS-fDywY2zPwXlrb:/home/alfred/.cache/uv/archive-v0/zKTheZIblUKblIHq:/home/alfred/.cache/uv/archive-v0/0oYfnLum5o7lxH7f:/home/alfred/.cache/uv/archive-v0/I72leh8kvOwfxzxF:/home/alfred/.cache/uv/archive-v0/km5q1G6DQSLWVkaR:/home/alfred/.cache/uv/archive-v0/q2KGeVV7WpodnnBE:/home/alfred/.cache/uv/archive-v0/H6nw76zWZtAyqp8H:/home/alfred/.cache/uv/archive-v0/tnPDiOo2cFPD0KWg /home/alfred/alfred-development-lab/milestone2/.test-venv/bin/python -m pytest -q -rs -p no:cacheprovider --basetemp=/tmp/task-a-contract-investigation-final tests/test_reply_binding.py tests/test_sidecar_spool.py tests/test_durable.py tests/test_security_contracts.py
```

The isolated interpreter and cached libraries predate this investigation;
pytest cache is disabled and temporary files stay under `/tmp`. The Node
runtime is the available installed executable; tests execute it with only
synthetic input and do not connect to Photon.

## Coverage and limits

| Scenario | Test/evidence | What it shows |
| --- | --- | --- |
| Overlapping same-chat events and delayed replies | `tests/test_reply_binding.py::test_overlapping_same_chat_turns_keep_original_handles` | The proposed adapter's separate async tasks retain distinct handles in the synthetic case. It does not establish protected turn authority. |
| Queued drain and merged event | `tests/test_reply_binding.py::test_installed_gateway_drain_rebinds_queued_job_to_its_own_event` | New drain tasks can rebind; a merged event is rejected by the proposed adapter. |
| In-band queued follow-up | `tests/test_reply_binding.py::test_installed_in_band_followup_inherits_first_turn_binding` | **Observed counterexample:** the installed recursive follow-up executes under the opening turn's context. |
| Handle and destination substitution | `tests/test_security_contracts.py::test_known_handle_substitution_is_currently_accepted_at_restricted_boundary`; `tests/test_reply_binding.py::test_missing_or_mismatched_turn_context_is_denied` | An arbitrary second live handle can be submitted by the same Hermes peer; model-visible handles are insufficient authority. The adapter rejects missing/mismatched ambient context only in the honest path. |
| Crash before first spool fsync | `tests/test_sidecar_spool.py::test_crash_before_first_spool_fsync_leaves_no_replayable_event` | Local spool has no committed event after injected fsync failure. **Provider redelivery is untested and unproven.** |
| Crash after spool commit and local replay | `tests/test_sidecar_spool.py::test_crash_replay_uses_same_delivery_id_without_read_receipt`; `tests/test_durable.py::test_durable_acceptance_precedes_sidecar_ack_and_reuses_handle` | Committed local record replays with stable identity, without a premature read receipt. |
| Reconnect and SDK catch-up | `tests/test_security_contracts.py::test_installed_sdk_in_process_reconnect_uses_volatile_catchup` | Installed `resumableOrderedStream`, fed fake events, emits one live event, replays one synthetic missed event after disconnect, and consumes a later live event. This is **in-process SDK behavior only**. Source-backed tests also confirm no persistent high-level cursor and silent gap acceptance on cursor rejection. |
| Sequence gaps | `tests/test_security_contracts.py::test_message_only_sequences_cannot_certify_gap_free_global_log` | A gap in filtered message sequences can reflect another event type; full log and provider retention are needed. |
| Reconciliation uncertainty | `tests/test_durable.py::test_provider_unverified_event_never_reaches_hermes_or_gateway`, `::test_unanswered_event_survives_ttl_and_restart_for_reconciliation`, `::test_unresolved_journal_capacity_fails_closed` | Current staging holds real-provider-unverified observations and retains unresolved records across restart. There is no approved promotion path. |

Results: **32 passed, 0 failed, 0 skipped** (final command above). The
earlier 31-test run preceded the added installed-SDK reconnect probe. Source
hashes in `AFFECTED_UPSTREAM_SOURCE_PATHS.md` were reproduced with `sha256sum`
over the 15 installed files. The broader staging and Hermes regression suites
were outside this focused investigation and were not rerun; historical
v0.1.4 results remain in `TEST_RESULTS.md` and are not treated as current
passes.

## Unverified and separately authorized work

- Provider retention period and low-water sequence; complete replay across a
  process crash before first local fsync; `catchUp` completion and atomic
  handoff to live subscription; message-history completeness.
- Live SDK reconnect, cursor rejection, dropped message, sequence gap and
  delayed history visibility in an authorized disposable Photon project.
- End-to-end exact event/result attestation under separate trusted processes
  or one-job OS-isolated workers, including cancellation and tool sends.
- Cross-UID Unix socket, credential and Gateway inbox permissions and crash
  recovery in an isolated Linux acceptance environment.

Synthetic test success is not a Photon provider guarantee or OS isolation
proof. The disposition is **architecture decision required** before a new
staging implementation or release can be accepted.
