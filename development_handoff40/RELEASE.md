# handoff.40 release pins and deployment procedure

Built by `development_handoff40/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.40` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.40.tar.gz` | `06db7b3797847bb313034cef8a017c7d8ea09afad48ce4be451431a9771bb7fc` |
| Release `MANIFEST.sha256` | `d1d620c3d6e5b5d3d0eaf61873f42165098492988f564212ab5ebb8a0a8de63a` |
| Release `development_handoff40/install_patch.py` | `e9ee0124f394d146b0585852685545e1f3e03f8905c6c9cda655e464c8a88b39` |

Staging evidence:
- Gate 1 passes in full, including `handoff40` (57 tests). `staging-tests.xml` holds 87 targeted tests.
- `test_planning_waits_for_a_gateway_run_that_holds_the_lock` reproduces T-0010's `GatewayBusy` without the fix and passes with it.
- Both pins match the live host on 2026-10-19.

## Deployment

```bash
git -C /home/alfred/alfred-development-v1 pull --ff-only
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 40
```

Type `06db7b379784`. Expect two `OK` lines.

```bash
sudo alfred-dev-ops resume
```

## Rollback

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops rollback 40
```
