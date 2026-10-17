# Task A v0.1.4 corrective verification — 2026-10-14

This is **not** a passing release report. There is no v0.1.4 archive or
manifest because H3 and H4 remain incomplete. Tests use synthetic SDK
events; they establish no live Photon authentication or provider replay.

## Commands and observed results

The staging suite used the already available isolated pytest interpreter and
cached dependency paths listed in the historical v0.1.3 command below. The
exact v0.1.4 command was:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 TMPDIR=/tmp PYTHONPATH=/home/alfred/.cache/uv/archive-v0/DK4n9G7xyVKZZ3KJ:/home/alfred/.cache/uv/archive-v0/Vd_UqZgwiCKPnjqT:/home/alfred/.cache/uv/archive-v0/yS-fDywY2zPwXlrb:/home/alfred/.cache/uv/archive-v0/zKTheZIblUKblIHq:/home/alfred/.cache/uv/archive-v0/0oYfnLum5o7lxH7f:/home/alfred/.cache/uv/archive-v0/I72leh8kvOwfxzxF:/home/alfred/.cache/uv/archive-v0/km5q1G6DQSLWVkaR:/home/alfred/.cache/uv/archive-v0/HXHkS5Ryw6x2BjKb:/home/alfred/.cache/uv/archive-v0/q2KGeVV7WpodnnBE:/home/alfred/.cache/uv/archive-v0/H6nw76zWZtAyqp8H:/home/alfred/.cache/uv/archive-v0/tnPDiOo2cFPD0KWg /home/alfred/alfred-development-lab/milestone2/.test-venv/bin/python -m pytest -q -rs -p no:cacheprovider --basetemp=/tmp/task-a-v014-staging-final tests -k 'not disposable_gateway_files_one_unapproved_task_after_broker_write'
PYTHONDONTWRITEBYTECODE=1 python3 make_photon_patch.py
git -C /home/alfred/.hermes/hermes-agent apply --check /home/alfred/alfred-development-lab/milestone2/task-a/patches/photon-secure-front.proposed.patch
```

Result: **101 passed, 5 skipped, 1 deselected**. Four skipped tests require
Unix socket bind and one requires socketpair send, both denied by the current
sandbox. The deselected test invokes the real Gateway dispatcher and would
create a development task record, which this authorization forbids. Patch
regeneration produced SHA-256
`dddd605e22778d761275b9050870c543800bc378bdd92ed4843af2b1d79a1533`;
`git apply --check` succeeded without modifying installed Hermes. The suite
includes Linux no-replace rename commit-boundary injections, journal
crash/restart, queued same-chat binding, held no-read sidecar acknowledgement,
forged-handle audit and repeated-denial audit. It does not establish a real
provider contract or cross-UID confinement.

The unchanged installed Hermes Photon suite was rerun with Node 26.7.0 on
PATH, cached Python dependencies, pytest cache disabled and a `/tmp` base.
The command used `timeout 60s`, the same pytest interpreter and `PYTHONPATH`
above, and targeted
`/home/alfred/.hermes/hermes-agent/tests/plugins/platforms/photon`.
Result: **79 passed, 71 failed**, 65 warnings. A focused rerun established
that an async failure reports missing `pytest-asyncio`; the remaining
`test_sidecar_patch_failure_still_reaches_health_endpoint` fails before the
adapter starts because the sandbox returns `EPERM` from `socket.socket()`.
The broader suite did complete in 4.73 seconds; the previous stalled media
run remains unexplained under a full dependency environment. The 71 failures
are not classified as candidate regressions or passes. A complete patched
Hermes suite was not run.

An isolated v0.1.4 virtual environment was created under this workspace with
the installed Python interpreter, but `uv pip install pytest==8.4.2
pytest-asyncio==1.2.0` could not resolve PyPI in the restricted network. No
escalation was requested. `pytest-asyncio` was not available in the local
cache; consequently a reproducible complete baseline/patched environment is
unfinished. Node 26.7.0 is installed at
`/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node`.

```sh
cd /home/alfred/alfred-development-lab/milestone2/task-a/dist
sha256sum -c alfred-task-a-staging-0.1.2.tar.gz.sha256 alfred-task-a-staging-0.1.3.tar.gz.sha256
```

Both immutable prior archive checks passed. There is no v0.1.4 archive or
payload hash to verify.

## Historical v0.1.3 result

No installed Hermes, Photon or Gateway file, identity or service was changed.
No real Photon message, protected Gateway operation, Task B work or Gateway
task creation occurred. These are synthetic and disposable tests, not live
Photon authentication or production isolation.

## Successful checks

From this Task A workspace:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 make_photon_patch.py
git -C /home/alfred/.hermes/hermes-agent apply --check /home/alfred/alfred-development-lab/milestone2/task-a/patches/photon-secure-front.proposed.patch
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 TMPDIR=/tmp PYTHONPATH=/home/alfred/.cache/uv/archive-v0/DK4n9G7xyVKZZ3KJ:/home/alfred/.cache/uv/archive-v0/Vd_UqZgwiCKPnjqT:/home/alfred/.cache/uv/archive-v0/yS-fDywY2zPwXlrb:/home/alfred/.cache/uv/archive-v0/zKTheZIblUKblIHq:/home/alfred/.cache/uv/archive-v0/0oYfnLum5o7lxH7f:/home/alfred/.cache/uv/archive-v0/I72leh8kvOwfxzxF:/home/alfred/.cache/uv/archive-v0/km5q1G6DQSLWVkaR:/home/alfred/.cache/uv/archive-v0/HXHkS5Ryw6x2BjKb:/home/alfred/.cache/uv/archive-v0/q2KGeVV7WpodnnBE:/home/alfred/.cache/uv/archive-v0/H6nw76zWZtAyqp8H:/home/alfred/.cache/uv/archive-v0/tnPDiOo2cFPD0KWg /home/alfred/alfred-development-lab/milestone2/.test-venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/tmp/task-a-remediate-final-2 tests -k 'not disposable_gateway_files_one_unapproved_task_after_broker_write'
```

Final suite count: **78 passed, 5 skipped, 1 deselected**. It covers deterministic
upstream patch reproduction, Python AST and Node syntax, synthetic spool and
journal failure injection, disposable child launch/shutdown, systemd parser,
Gateway envelope contract, Evidence Bridge hashes, and negative security tests.

## Installed Hermes Photon baseline investigation

The following equivalent commands set all inputs explicitly and ran from
`/home/alfred/.hermes/hermes-agent`:

```sh
export HOME=/home/alfred/alfred-development-lab/milestone2/task-a/.regression-home
export TMPDIR=/home/alfred/alfred-development-lab/milestone2/task-a/.regression-home
export PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export PYTHONPATH=/home/alfred/.cache/uv/archive-v0/DK4n9G7xyVKZZ3KJ:/home/alfred/.cache/uv/archive-v0/Vd_UqZgwiCKPnjqT:/home/alfred/.cache/uv/archive-v0/yS-fDywY2zPwXlrb:/home/alfred/.cache/uv/archive-v0/zKTheZIblUKblIHq:/home/alfred/.cache/uv/archive-v0/0oYfnLum5o7lxH7f:/home/alfred/.cache/uv/archive-v0/I72leh8kvOwfxzxF:/home/alfred/.cache/uv/archive-v0/km5q1G6DQSLWVkaR:/home/alfred/.cache/uv/archive-v0/HXHkS5Ryw6x2BjKb:/home/alfred/.cache/uv/archive-v0/q2KGeVV7WpodnnBE:/home/alfred/.cache/uv/archive-v0/H6nw76zWZtAyqp8H:/home/alfred/.cache/uv/archive-v0/tnPDiOo2cFPD0KWg
timeout 30s /home/alfred/alfred-development-lab/milestone2/.test-venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/home/alfred/alfred-development-lab/milestone2/task-a/.regression-home/pytest-auth tests/plugins/platforms/photon/test_auth.py
timeout 45s /home/alfred/alfred-development-lab/milestone2/.test-venv/bin/python -m pytest -q -p no:cacheprovider --basetemp=/home/alfred/alfred-development-lab/milestone2/task-a/.regression-home/pytest-broad tests/plugins/platforms/photon
timeout 5s /home/alfred/alfred-development-lab/milestone2/.test-venv/bin/python -c 'import asyncio; print(asyncio.run(asyncio.to_thread(lambda: 1)))'
```

The auth module passed **19/19** against unchanged installed source. The
broad run finished **64 passed, 76 failed, 8 errors, 2 skipped** and is not a
passing regression. This harness lacks `pytest-asyncio`, and Node was absent
from its PATH; eight errors include Node invocation failure. Many async tests
failed or skipped before adapter behavior was exercised. The standalone
`asyncio.to_thread` command timed out after five seconds (exit 124),
reproducing the sandbox thread problem behind the earlier stalled media test.
The legacy media tests assert `/send-attachment` path semantics removed from
Task A mode. Their compatibility contract needs explicit review, not silent
exclusion. No upstream test result is represented as patched-adapter success.

## Unexecuted or sandbox-blocked checks

- One staging test invokes the real Gateway dispatcher and creates a
  disposable task record. It was deselected because this run forbids even lab
  development task creation.
- Four Unix socket bind tests and one socketpair send test skipped after
  sandbox `EPERM`. They require a separately authorized isolated Linux host.
- Cross-UID inbox ACL and Gateway reads, actual systemd socket activation,
  service namespace and credential ownership, 32-client slowloris soak, real
  Photon stream replay/read receipt, and patched Hermes compatibility are
  unverified. Evidence Bridge v0.2.1 hashes and copies have staging coverage;
  live two-tool behavior under the proposed Hermes UID remains pending.

## Release verification

The immutable archive's outer SHA-256 and all payload SHA256SUMS entries are
verified after packaging. The exact digest and verification result are stored
in `dist/RELEASE_STATUS.txt` beside the archive. The v0.1.2 archive and
checksum remain unchanged.
