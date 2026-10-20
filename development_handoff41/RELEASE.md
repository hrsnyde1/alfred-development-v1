# handoff.41 release pins and deployment procedure

Built by `development_handoff41/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.41` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.41.tar.gz` | `8e6c5b53e9f2f36701162d8de285467aced3eb7a0eaa7c457cd5cb0d04a15b83` |
| Release `MANIFEST.sha256` | `552d18a2dde2cf9d701bd27090130461722cd3243b9e0b48764c1f26f92f0266` |
| Release `development_handoff41/install_patch.py` | `6b3a56e531415555c52830eeebb3f1dd2d950f6ef09ff4329ebed70ed2be3bd9` |

Staging evidence:
- Gate 1 passes in full, including `handoff41` (43 tests). `staging-tests.xml` holds 77 targeted tests.
- A dry run of T-0013's real inputs keeps its five code criteria and moves the three that held it.
- Both pins match the live host on 2026-10-20.

## Deployment

```bash
git -C /home/alfred/alfred-development-v1 pull --ff-only
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 41
```

Type `8e6c5b53e9f2`. Expect two `OK` lines.

```bash
sudo alfred-dev-ops resume
```

## Rollback

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops rollback 41
```
