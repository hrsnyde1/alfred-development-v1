# handoff.37 release pins and deployment procedure

Built by `development_handoff37/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.37` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.37.tar.gz` | `787f905630e2c54738c835282142c95f8675b80a49f16664efa2a0ae86286d7b` |
| Release `MANIFEST.sha256` | `2237b454e42924d1f3ac99dd9a2ceaef52c10efad1b2bb9f3f5500579ee32dbd` |
| Release `development_handoff37/install_patch.py` | `4293a73340d6c2ae91e55066895b9276c7d4242c0adb4a2554db95a4bd2f259f` |

Staging evidence:
- Gate 1 passes in full, including `handoff37` (48 tests). `staging-tests.xml` holds 105 targeted tests.
- All four pins match the live host on 2026-10-19.
- A dry run of demo-site T-0008's real inputs plans Frontend on `app.js`, `index.html` and `styles.css`. The installed `role.py` refuses the same inputs.

## Deployment
Make sure the checkout is current first (`git -C /home/alfred/alfred-development-v1 pull --ff-only`).

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 37
```

Type `787f905630e2`. Expect two `OK` lines.

```bash
sudo alfred-dev-ops resume
```

## Rollback

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops rollback 37
```
