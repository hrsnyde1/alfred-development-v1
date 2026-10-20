# handoff.42 release pins and deployment procedure

Built by `development_handoff42/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.42` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.42.tar.gz` | `e1a946d8e6d403ed7b930007d6b65ceffc94290a71be26fe5b03704b3c90cc1f` |
| Release `MANIFEST.sha256` | `ccb441ebbd5e9ba6d5a41eeeeac18bca754a7646f68c4e2c7ed85233e820e88e` |
| Release `development_handoff42/install_patch.py` | `01c3306bf21964baa1545b2623be71526f88cf782e4cbb1943a2f574bb02b407` |

Staging evidence:
- Gate 1 passes in full, including `handoff42` (78 tests) and `handoff38`. `staging-tests.xml` holds 86 targeted tests.
- On 2026-10-20, five of six pins match the live host. The sixth is handoff.41's `role.py`, which matches once handoff.41 is installed.

## Deployment
handoff.41 first. Do not install handoff.38.

```bash
git -C /home/alfred/alfred-development-v1 pull --ff-only
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 42
```

Type `e1a946d8e6d4`. Expect `OK` lines and an intake restart.

```bash
sudo alfred-dev-ops resume
```

## Rollback

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops rollback 42
```
