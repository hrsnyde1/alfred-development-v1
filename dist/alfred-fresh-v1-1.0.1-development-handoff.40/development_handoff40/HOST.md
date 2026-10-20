# handoff.40 host procedure: planning waits for the Gateway lock

## Why
demo-site T-0010 (2026-10-19) was held at planning as `plan: python/python_failed`.
- The Gateway timer (`alfred-development-gateway.service`) runs every seven seconds and
  holds the gateway lock for about a second.
- T-0010's plan step started at 23:31:20.974, 3 ms before a timer run at 23:31:20.977.
  `prepare_plan` takes that lock with the non-blocking `gateway_lock`, which raised
  `GatewayBusy` ("the caller may retry") at once. Nothing retried.

That gives roughly a one-in-six chance on every plan. A dry run of T-0010's inputs a
few minutes later planned Frontend normally.

## What changes (one file, no restart)

| Destination | Change |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/role.py` | `prepare_plan` uses the Gateway's own `acquire_gateway_lock`, which waits up to five seconds |

## Order
handoff.39 first. This release pins its `role.py`.

T-0010 stays held; resend the request after installing.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 40`.
