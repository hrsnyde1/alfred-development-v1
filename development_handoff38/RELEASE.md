# handoff.38 release pins and deployment procedure

Built by `development_handoff38/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.38` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.38.tar.gz` | `a95c7d0547ea2e71b38012085a318b276fa5e60aa40347e2c1d0e577703817c3` |
| Release `MANIFEST.sha256` | `116f61fc1b58c166aeb7f27e8f965d3de8f79016fa2a039f613b5c97b3c2545f` |
| Release `development_handoff38/install_patch.py` | `9a18d57d01ed3e081feedf64079f73fccc217e1d147297da29669d5ef75e65d5` |

Staging evidence:
- Gate 1 passes in full, including `handoff38`. `staging-tests.xml` holds 135 targeted tests.
- All four `BASE` pins match the live host on 2026-10-19. The `role.py` dependency is handoff.37's installed-after hash.
- A real `prepare_plan` refusal, run through the worker boundary, is recorded as `plan_refusal/clarification_required`. It produces exactly one owner text and is never resent, even when the send does not answer.

## Deployment
Install handoff.37 first. Make sure the checkout is current first (`git -C /home/alfred/alfred-development-v1 pull --ff-only`).

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 38
```

Type `a95c7d0547ea`. Expect four `OK` lines. The intake restarts.

```bash
sudo alfred-dev-ops resume
```

## Rollback

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops rollback 38
```
