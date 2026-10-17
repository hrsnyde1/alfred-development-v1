# Deployment: handoff.16, handoff.17 and handoff.18

These replace the earlier attempts at handoff.13 and handoff.15, which both refused on
the host because they checked Gateway-owned files as root-owned. Nothing was changed by
those attempts. handoff.14 is already installed.

| Release | What | Archive SHA-256 (type the first 12 characters) |
| --- | --- | --- |
| handoff.16 | Team skills (handoff.13 with the owner fix) | `7449f400afafd21766d8939183578e9781148907f304ecefa262899132c169e5` |
| handoff.17 | The fix loop (handoff.15 without Gateway pins) | `1d46351f26179edbd886ebcf0a07efd8160fea3cad2c161a5d6f09ef170e2bc6` |
| handoff.18 | Demo site repository writable in the sandbox | `7b78edea829b2a969c7ba2c876348536cdd5256fb1648f480ab8e96a56377ab7` |

Each archive rebuilds byte for byte (`build_release.py --reproduce`). Gate 1 passes,
including the handoff16, handoff17 and handoff18 suites. Every pin the three installers
check was dry-run against the live host as alfred (owner, mode, link count and hash),
with no refusals.

## Steps (in this order; stop at the first line that does not match)

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 16
```

Type `7449f400afaf`. Expect six `OK` lines, `"overall": "PASS"`, `"pause": "still set"`.

```bash
sudo alfred-dev-ops install 17
```

Type `1d46351f2617`. Expect ten `OK` lines, the intake restart, `"overall": "PASS"`,
`"pause": "still set"`.

```bash
sudo alfred-dev-ops install 18
```

Type `7b78edea829b`. Expect one `OK` line and `"pause": "still set"`.

```bash
sudo systemctl daemon-reload
```

```bash
sudo alfred-dev-ops resume
```

Then send the dark-mode request again from your phone, for example "Add a light/dark
mode toggle to the demo site". The earlier attempt (T-0001) keeps its recorded planning
failure as evidence; the new request becomes the next demo-site task.

## Rollback
`sudo alfred-dev-ops pause`, then roll back in reverse order: `rollback 18`,
`systemctl daemon-reload`, `rollback 17`, `rollback 16`.
