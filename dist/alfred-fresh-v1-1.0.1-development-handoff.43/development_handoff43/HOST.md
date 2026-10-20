# handoff.43 host procedure: a watchdog for stalled iMessage inbound (Photon)

## Why
On 2026-10-19/20 Hayden's texts stopped reaching Alfred while `alfred-photon.service`
and `alfred-hermes.service` both stayed `active` and the sidecar still listened on
127.0.0.1:8789. `sudo systemctl restart alfred-photon.service` fixed it each time; it
also restarts Hermes, which `Requires=` Photon. This release adds a root timer that
makes that restart itself, but only on a confirmed stall, and logs why.

## What the journals show (read-only, 2026-10-18 to 2026-10-20)
- **2026-10-19 04:46 to 21:53, one long outage with a log signal.** The sidecar logged
  `[spectrum.stream] WARN stream interrupted; reconnecting` for the
  `imessage.messages:shared` stream (twice, then a `ConnectionError ... UNAVAILABLE`),
  and `INFO stream recovered` only at 21:53:11. No turn ran in those 17 hours; the first
  came three seconds after the recovery line.
- **22:11 to 23:01, 23:06 to 23:21 and 23:33 to 00:20, three silent stalls.** Neither
  unit logged anything: no stream line, no error. Each ended with a restart of Photon
  (Hermes stops first, then Photon, then both start). These leave no log signal, so the
  watchdog reads the sockets instead.
- `photon-sidecar: inbound stream ended — re-subscribing` is **not** a stall signal: it
  appears only on shutdown, right after `received SIGTERM`.

## How it decides
Every two minutes, without credentials, using `ss` filtered by each unit's cgroup and
the journal of Photon's current run:

| Check | Stall when | Healthy, even on a quiet line |
| --- | --- | --- |
| stream | `imessage.messages` interrupted with no `stream recovered` for 10 minutes | A reconnect recovers in about a second |
| upstream | The sidecar has no connection to Photon, or it has received nothing for 5 minutes | Photon sends on it every few seconds: about 1,000 packets in the 1 h 53 min after the 00:20 restart (10 turns), and never more than 17 s apart in 90 samples over 15 minutes |
| consumer | No Hermes `/inbound` connection to 127.0.0.1:8789 with a fresh heartbeat (90 s) | The sidecar writes a heartbeat to it every 25 s |

- A socket finding must be seen on two consecutive runs; the stream finding must have
  lasted 10 minutes. Nothing is judged within 3 minutes of Photon starting, or while
  either unit is not `active` (systemd's `Restart=always` handles those).
- Then it runs `systemctl restart alfred-photon.service`. At most one restart per
  30 minutes and 4 a day. Past that it logs `stall_confirmed_restart_withheld` once,
  naming the command for you, and does nothing else.
- If Hermes leaves bytes unread on its `/inbound` connection on two runs in a row, that
  is logged as `hermes_unread_bytes` but never acted on: it is evidence for the next
  investigation, not a confirmed stall.
- The silent stalls happened before these checks existed, so whether the upstream or
  consumer check would have caught them is not proven. If one recurs and the watchdog
  stays quiet, its log shows which legs looked healthy.

## What changes (three new files; nothing installed changes)

| Destination | Purpose |
| --- | --- |
| `/usr/local/lib/alfred-fresh-v1/fresh_v1/photon_watchdog.py` | The checks, the rate limit and the restart |
| `/etc/systemd/system/alfred-photon-watchdog.service` | Root oneshot: read-only system, no home, no IP sockets (Unix and netlink only), its own state directory |
| `/etc/systemd/system/alfred-photon-watchdog.timer` | Runs it 5 minutes after boot, then every 2 minutes |

`alfred-dev-ops install` writes the files but only restarts units it is allowed to
(`alfred-development-intake.service`). It does not reload systemd or enable a timer, so
you do those two steps by hand after the install (see RELEASE.md).

## Watching it

```bash
journalctl -t alfred-photon-watchdog -n 20 --no-pager
```

`inbound_ok` once an hour means it is running and sees nothing wrong. `stall_suspected`
means one run saw something. `stall_confirmed_restarting` and `restarted` mean it acted.

## Turning it off
`sudo systemctl disable --now alfred-photon-watchdog.timer`. Nothing else depends on it.

## Rollback
`sudo systemctl disable --now alfred-photon-watchdog.timer`, then `sudo alfred-dev-ops
pause`, `sudo alfred-dev-ops rollback 43`, `sudo systemctl daemon-reload` and
`sudo alfred-dev-ops resume`.
