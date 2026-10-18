# handoff.28 release pins and deployment procedure

Built by `development_handoff28/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.28` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.28.tar.gz` | `6f6149ae7cfbc94cf8df480bd118cb53aa3d3103052b89e61e6239fcf9cc1418` |
| Release `MANIFEST.sha256` | `e8b197d45f9bb98acb351c8e15aa523bd0a034fdbfcdad7bc27c3451b45b7dae` |
| Release `development_handoff28/install_patch.py` | `4a287a6981ceead26b9f97180948a7f5cdbb23a6f14bd905c877a920c000e3e7` |

Staging evidence: Gate 1 passes, including `handoff28`, whose tests read every developer
report already on the host. Both pins match the live host with handoff.27 installed.

## Deployment

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 28
```

Type `6f6149ae7cfb`. Expect one `OK` line.

```bash
sudo alfred-dev-ops resume
```

The timer picks up the new file on its next run, within 20 seconds.
