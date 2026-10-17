# Independent review response

The prior v0.1.3 review failed. The current corrective workspace is **not**
a v0.1.4 release. `V014_CORRECTIVE_STATUS.md` contains the H1-H4/M1-M2
matrix, exact code/test evidence and remaining blockers. The v0.1.2 response
below is historical and must not be read as current acceptance.

## Historical v0.1.2 response for v0.1.3

These are staging dispositions, not production acceptance. See
`TEST_RESULTS.md` for exact commands and sandbox limits.

| Finding | Staging disposition | Correction and evidence | Remaining gate |
| --- | --- | --- | --- |
| H1 protected launch | FIXED | `task_a/service.py`, `templates/systemd/alfred-photon-intake.service`, `tests/test_service.py` supply an executable entry point, credential handoff, one-child supervision, health/restart and shutdown. | Actual activated socket, protected UID and full SDK launch on disposable Linux. |
| H2 inbox permissions | FIXED | `task_a/transport.py`, `templates/permissions/paths.json`, `tests/test_broker_transport.py` use `O_PATH`, setgid `0640`, no-clobber publication and durable retry. | Measure separate broker/Gateway UIDs, ACL mask and Gateway read in isolated Linux. |
| H3 handle race | FIXED | `make_photon_patch.py`, `tests/test_reply_binding.py`, `task_a/durable.py` bind each async turn to its exact handle, reject missing/mismatched context and preserve one-shot state over restart. | Run patched real Hermes adapter with concurrent delayed turns. |
| H4 durable inbound | PARTIALLY FIXED | `patches/photon-durable-spool.mjs.txt`, `task_a/durable.py`, `task_a/photon_front.py` spool and journal before ack/read; bounded retry, explicit rejection, unavailable/delayed states and crash tests. | Prove SDK redelivery after crash before spool fsync; run real read-receipt and reconnect faults. |
| M1 exhaustion | FIXED | `task_a/photon_front.py`, `task_a/durable.py`, `task_a/audit.py`, `tests/test_photon_front.py`, `tests/test_durable.py` cap requests, clients, handlers, queue, journal and audit. | Kernel-level slow-client soak and service memory limits in isolated Linux. |
| M2 audit | PARTIALLY FIXED | `task_a/audit.py`, `task_a/service.py`, `tests/test_durable.py` record code-only denials/failures/retries with owner-only bounded storage; Node stdout/stderr are discarded. | Independently test log rotation, read-receipt failure telemetry and SDK diagnostic privacy. |

The legacy Photon broad suite is not a passing regression: 76 failures and 8
errors occurred with the available incomplete harness; `asyncio.to_thread`
also timed out in this sandbox. A separately authorized, network-independent
test image with `pytest-asyncio`, the pinned Node binary on PATH and working
thread/socket primitives must run both unmodified and patched suites. Media
tests describe the legacy path-bearing route and require an explicit Task A
expectation, not silent suppression.
