# handoff.39 release pins and deployment procedure

Built by `development_handoff39/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.39` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.39.tar.gz` | `3cb6d7e321dce934f38094b06a04d928edf9905e2bcafc59d1380dec6fe285ac` |
| Release `MANIFEST.sha256` | `8aa6f3ea0e05c422a24739963d65e1ab852161bb065d5c2708b78f503449951f` |
| Release `development_handoff39/install_patch.py` | `379089d3e7a1ea5c23aba3bbb878a44b64804ea49457c8db3453dc992647a071` |

Staging evidence:
- Gate 1 passes in full, including `handoff39` (73 tests) and `handoff38`.
- `staging-tests.xml` holds 150 targeted tests.
- All four pins match the live host on 2026-10-19.
- A dry run of demo-site T-0009's real inputs plans Frontend, records `["frontend"]` in the plan, and passes the schema this release installs.

## Deployment

```bash
git -C /home/alfred/alfred-development-v1 pull --ff-only
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 39
```

Type `3cb6d7e321dc`. Expect `OK` lines and an intake restart.

```bash
sudo alfred-dev-ops resume
```

## Rollback

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops rollback 39
```
