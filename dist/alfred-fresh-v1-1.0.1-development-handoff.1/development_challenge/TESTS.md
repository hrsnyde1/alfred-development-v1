# Focused staging verification

Final run: **176 Python tests passed, 45 subtests passed; 3 Node tests passed**.
No skipped tests in this selection. New tests: 40 delivery/handoff tests, 15
installation/rollback tests and 3 Node observer tests.

The selection intentionally excludes specialist execution, authenticated model
probes, Publisher operations and completion sends. Temporary Git repositories
are local fixtures. Photon HTTP and Unix sockets, SDK events and owner events are
mocked. A filesystem-namespace probe runs only an isolated permission-check
process with protected production paths mounted read-only; no worker is started.

```bash
cd /home/alfred/alfred-development-lab/milestone2/task-a
mapfile -t DEVELOPMENT_TESTS < development_challenge/test-selection.txt
/home/alfred/Git/alfred/.venv/bin/python -m pytest -q "${DEVELOPMENT_TESTS[@]}" \
  --junitxml=development_challenge/staging-tests.xml
/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node \
  --test --test-reporter=tap --experimental-test-isolation=none \
  development_challenge/tests/development-observe.test.mjs
```

Run the existing namespace fixture outside Codex's filesystem sandbox; do not
loosen host permissions or enable namespaces to make it pass. The Node flag runs
the three deterministic cases in-process so their virtual-time assertions are
reported individually; it creates no socket or SDK connection.

Coverage includes:

- Genuine native-ID success, fsynced intent before send, immutable ACK/index.
- Slow ACK and both actual root-client implementations waiting beyond 20 seconds.
- TCP/preflight refusal vs provider errors whose side effects cannot be proven.
- Timeout after possible transmission, null/malformed ACK, redacted outcomes.
- Restart/race duplicate prevention and interruption before send, after
  transmission, after ACK, before atomic receipt publication and before indexing.
- ACK-only native replies with owner/DM/phrase/time/thread/forwarding/replay guards.
- Grant single use, task slot independent of mutable scope/plan/DM.
- Existing poll leaving a historical uncertain attempt unchanged while handling
  a separately filed T-0004 fixture; T-0001/T-0002 fixtures remain intact.
- All seven installation failure positions, explicit repeatable rollback,
  inventory/host/dependency drift, and rejection of unexpected rollback paths.

The first broader staging run found the expected old invalid-ACK assertion and a
historical-grant fixture seeded with the modern issuer; these now assert the new
typed uncertain failure and use the pinned old issuer for legacy compatibility.
The namespace probe initially failed within Codex sandbox and passed outside it
without any host change. Historical diagnostics-overlay tests now use their
immutable diagnostic release, rather than the newer functional source. Final
selected suite above passed. No production code was executed as a service.

Python F/E9 checks pass for changed runtime files. New tests and installer pass
the configured full lint rules. The existing Intake's unrelated style findings
were not rewritten. The release pins all payload bytes; tests are reproduced
from the Development Lab with its existing dependencies and archived fixtures.
