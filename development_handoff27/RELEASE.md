# handoff.27 release pins and deployment procedure

Built by `development_handoff27/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.27` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.27.tar.gz` | `706aa8001ac6a5af3392f8652fb894c37e5ae0295857f2de89e74e1cf671eb1c` |
| Release `MANIFEST.sha256` (10 payload files) | `ee22b09c09d12ff70eebe9f25106d2e04920fbd998afbaa3c4f48945b377e041` |
| Release `development_handoff27/install_patch.py` | `8cdf398ceef067abe4e7ca0681c9ecc77d7388a44809df6bf71e110aede92225` |

Staging evidence: Gate 1 passes, including `handoff27`. `systemd-analyze verify`
accepts both units. Its one pin (`upgrade.py`) matches the live host.

## Before installing
In Telegram, the squads bridge needs:
1. The Dev CTO's bot and each agent's bot stored with `bash add-squad-bots.sh` (from
   the bridge folder). At least `hub`, `cto` and `qa`. Agents without a bot are spoken
   for by the CTO.
2. A group per squad with the hub and those bots added, linked by typing `/squad web-app`
   (Frontend, Backend, Full Stack) and `/squad ai-data` (AI/ML, Data Scientist, Data
   Engineer) in it.

## Deployment

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 27
```

Type `706aa8001ac6`. Expect three `OK` lines and `"pause": "still set"`.

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl enable --now alfred-dev-squads.timer
```

```bash
sudo alfred-dev-ops resume
```

Then text Alfred a demo-site request and watch the web-app chat.
