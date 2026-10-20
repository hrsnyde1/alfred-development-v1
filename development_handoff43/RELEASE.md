# handoff.43 release pins and deployment procedure

Built by `development_handoff43/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.43` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.43.tar.gz` | `dcd071c0b557d182a899df8406db237c2a2c3e94b71ab6ce7e77881f53e807a7` |
| Release `MANIFEST.sha256` (10 payload files) | `83bccc0c37da5d171bd6f7df43f6e2719d1419434b95ccfa784f7bed57d93c4d` |
| Release `development_handoff43/install_patch.py` | `1c30456fa8a72c61faff9bf0fcab73e750030df478e25752b369b5f4796d022b` |

Staging evidence:
- Gate 1 passes in full, including `handoff43` (17 tests, also in `staging-tests.xml`).
- `systemd-analyze verify` accepts both units. The checks were run read-only against
  the live host under the unit's sandbox settings (as `alfred`, through a user transient
  unit): they found the sidecar's one Photon connection and Hermes' `/inbound`
  connection and reported no stall. Replayed against the 2026-10-19 journal, the stream
  check finds the outage starting at 04:46:41, so it would have restarted Photon at about
  04:57 instead of the inbound staying down until 21:53.
- Its one pin (`upgrade.py`) matches the live host, and all three destinations are
  absent there today. It does not depend on any other handoff.
- Not exercised as root: the actual `systemctl restart` and the timer under PID 1.

## Deployment
`alfred-dev-ops` installs the three files but may only restart the intake, so it cannot
reload systemd or enable the timer. Those two steps are by hand.

```bash
git -C /home/alfred/alfred-development-v1 pull --ff-only
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 43
```

Type `dcd071c0b557`. Expect three `OK` lines, no restart and `"pause": "still set"`.

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl enable --now alfred-photon-watchdog.timer
```

```bash
sudo alfred-dev-ops resume
```

Check it ran once and saw nothing wrong (`inbound_ok`). The first run is right after
enabling; a run within 3 minutes of a Photon start logs nothing.

```bash
journalctl -t alfred-photon-watchdog -n 5 --no-pager
```

## Rollback

```bash
sudo systemctl disable --now alfred-photon-watchdog.timer
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops rollback 43
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo alfred-dev-ops resume
```
