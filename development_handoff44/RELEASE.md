# handoff.44 release pins and deployment procedure

Built by `development_handoff44/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.44` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.44.tar.gz` | `5c5ab1c8e1d24c770ed7f52fa546e969be8dcd4a65d223b48c16c3b32ddb0276` |
| Release `MANIFEST.sha256` (17 payload files) | `7cad04433bd27cc772ef59f9278d65ffe88d64f5c718320e30ffbb4ed0abaea3` |
| Release `development_handoff44/install_patch.py` | `0857086ccf9813f429743796f6ce3e97c561f664d5c7d928ef7dc626c2b21468` |

Staging evidence:
- What ran: the handoff.44 tests (38, in `staging-tests.xml`), the handoff.43 tests, and the
  checkout's whole `tests/` folder, in a clean container. Nothing failed that didn't
  already fail without this change. The tests that need the VM's installation (most of
  Gate 1) could not run there.
- `install_patch.py verify` accepts the release (17 files). On a fixture root, the
  installer installs over handoff.43's exact bytes and rolls back to them. It refuses
  without handoff.43 or without PAUSE.
- Not exercised: the real `systemctl restart` as root, the path unit under PID 1,
  `systemd-sysusers` and `systemd-tmpfiles` on the VM, and the board feed against the
  real task records.

## Deployment
Requires handoff.43 installed. `alfred-dev-ops` installs the files but only restarts the
intake, so the systemd steps are by hand.

```bash
git -C /home/alfred/alfred-development-v1 pull --ff-only
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 44
```

Type `5c5ab1c8e1d2`. Expect nine `OK` lines, no restart and `"pause": "still set"`.

```bash
sudo systemd-sysusers && sudo systemd-tmpfiles --create /etc/tmpfiles.d/alfred-photon.conf
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl enable --now alfred-photon-requests.path alfred-dev-board.timer
```

```bash
sudo alfred-dev-ops resume
```

Check the group, the spool and the two feeds:

```bash
getent group alfredphoton; ls -ld /var/lib/alfred-photon-requests
```

Expect `alfredphoton:x:…:alfredos,alfredmsg` and `drwxrwx--T root alfredphoton`.

```bash
sudo systemctl start alfred-photon-watchdog.service; ls -l /var/lib/alfred-photon-watchdog/stalls.json /var/lib/alfred-dev-board/workflows.json
```

Expect `-rw-r--r-- root root` for stalls.json and `-rw-r----- root alfred` for workflows.json.

Alfred OS picks up its group and the spool after its own update (hrsnyde1/alfred-hq,
"Photon stalls and the workflow board") and a restart. Hermes (so Alfred) picks up the
group on its next restart, which the first clear does anyway.

## Rollback

```bash
sudo systemctl disable --now alfred-photon-requests.path alfred-dev-board.timer
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops rollback 44
```

```bash
sudo systemctl daemon-reload
```

```bash
sudo alfred-dev-ops resume
```

The group and `/var/lib/alfred-photon-requests` stay. They do nothing without the path
unit, and handoff.43's watchdog ignores them.
