# Central CTO V1 staging and host acceptance

Status: staged only. No production file, service, task, Photon connection or approval state was changed. The existing Gateway timer remains the sole polling schedule. Its oneshot service first runs the existing `run-once`, then invokes `cto.py poll` under the same protected user and Gateway lock. Only trusted `filed` journal records are candidates. Repeated polls find the spec-hash-bound plan and do not send it again.

## Artifacts

- `cto.py`: one repository-aware Central CTO planner, protected plan store, and existing Photon `/send` delivery.
- `plan.schema.json`: structured plan contract; approval state is fixed to `awaiting_development_approval`.
- `gateway-cto-plan.proposed.patch`: adds read-only `gateway.py cto-plan T-NNNN --project ...` retrieval.
- `alfred-development-gateway.service`: replacement for the existing Gateway oneshot unit; the existing timer is unchanged.
- `bind_delivery.py`: one-time operator helper for a protected owner destination, checked against T-0001's original Photon DM digest. It does not send a message.

## Host installation, after separate operator approval

1. Record the current Gateway source revision, unit, and a protected backup of `.dev/bin/gateway.py`. Confirm the Gateway checkout matches the staged patch with `patch --dry-run -p1 -d /home/alfred/Git/alfred -i <staging>/v1_cto/gateway-cto-plan.proposed.patch`. Keep the current timer and existing Photon/Hermes units.
2. Install `cto.py`, `plan.schema.json`, and `bind_delivery.py` together in `/home/alfred/Git/alfred/.dev/bin/`, owned by the Gateway operator. Apply the reviewed patch to `.dev/bin/gateway.py`. Install the staged `alfred-development-gateway.service` over the existing unit. Do not enable a new timer or start a second Photon process.
3. As `alfred`, obtain the original SDK `space.id` for the owner's T-0001 direct message from the host's existing Photon/Hermes runtime evidence. Run `PYTHONPATH=/home/alfred/Git/alfred/.dev/bin:/home/alfred/Git/alfred/src /home/alfred/Git/alfred/.venv/bin/python -B /home/alfred/Git/alfred/.dev/bin/bind_delivery.py` and enter that ID at the hidden prompt. The helper refuses a space whose SHA-256 digest does not match both the staged T-0001 digest pin and the filed request's `origin.conversation_ref`. It creates `~/Alfred/gateway/v1-cto-delivery.json` with mode `0600`, reusing only the existing sidecar's ordinary send token and port. Stop if the original SDK destination cannot be established; do not guess or use model text as a destination.
4. After the operator authorizes a controlled acceptance run, reload the unit and let the **existing** Gateway timer invoke it once, or start that oneshot once. Check its `planned` and `delivered` counts. Run `gateway.py cto-plan T-0001 --project dev-001` to read the full protected plan. Confirm one owner text, one plan JSON, `approval_state: awaiting_development_approval`, and no task spec or repository change. Repeat the oneshot and confirm `existing: 1`, `planned: 0`, `delivered: 0` and no second owner text. Verify an ordinary Personal Alfred conversation still sends and receives normally through the existing sidecar.

Do not use `cto.py poll` on the live Gateway directory before the approved acceptance run: it would process T-0001 and attempt the owner message. No live acceptance was run in staging.

## Staging verification

Run with `PYTHONPATH=<staging>:/home/alfred/Git/alfred/.dev/bin:/home/alfred/Git/alfred/src PYTHONDONTWRITEBYTECODE=1 /home/alfred/Git/alfred/.venv/bin/python -m pytest -q -p no:cacheprovider v1_cto/tests`. The tests use temporary repositories, journal records, destinations and sidecar mocks. Latest result: **11 passed**. `ruff check` and `ruff format --check` passed on the three staged Python files. The real T-0001 journal record, spec, registry binding, and repository were inspected read only; no plan was persisted or message sent for T-0001.

## Expected T-0001 plan

Read-only inspection confirmed exactly one trusted filed outcome for request `a7881a72-b1d8-5179-973b-6e84efa4e62b` and a matching `proposed` spec in registry-bound `dev-001`. That repository contains `README.md`, `.gitignore`, and the task spec, with no website source or tests. The CTO therefore asks which authorized repository/path contains the website and lists no invented website files. A clarification or new authorized binding and refreshed plan is needed before any future development approval is meaningful.

## Delivery and approval semantics

The owner message ends with: “Here's how we'll build it. Do you approve development?” Its direct sidecar acknowledgment stores the outbound ID only. A send failure or timeout leaves the plan pending with `delivery.state: attempted_uncertain`; polling will not send again because a timed-out request may already have reached Photon. Reconcile the existing sidecar's delivery record and obtain a new owner instruction before any manual resend. No delivery state, Gateway filing confirmation, or ordinary conversation sets development approval. This milestone provides the explicit pending-approval contract in `CENTRAL_CTO.md`; it does not implement a Developer approval consumer.

## Targeted rollback

After an operator-approved rollback, restore only the backed-up Gateway unit and `.dev/bin/gateway.py`, remove only the three newly installed CTO files from `.dev/bin`, and reload the unit. Keep the original timer, Photon, Hermes, Gateway journal, canonical T-0001 spec and repository intact. Preserve `~/Alfred/gateway/cto-plans/` and the delivery configuration as protected evidence until the operator has reconciled whether a message was sent; neither grants approval. The original Gateway oneshot then resumes its prior filing-only behavior.
