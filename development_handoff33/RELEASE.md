# handoff.33 release pins and deployment procedure

Built by `development_handoff33/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.33` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.33.tar.gz` | `e43215ab1b76956b54afa4cc366a1f2cf3690c93d8380a154c290baf982d2163` |
| Release `MANIFEST.sha256` (16 payload files) | `1bea435bb8ed3a6da42351b5f6949abd7213c876d1aa1becd305fd7882660411` |
| Release `development_handoff33/install_patch.py` | `3c2e246165eecb4a9668eba2e2128427f19e23ee6216e47d532aa35e8086bec8` |

Staging evidence (`staging-tests.xml`): 163 passed, 1 skipped (the explicit real-model
acceptance test), across the plan-approval flow, handoff.33 transaction, one-yes,
auto-merge and undo, delegated approval, independent QA, squads, fresh V1 and Developer
execution suites. One upgrade test (the installed-after pins against the built tree) can
only run after the build; it passes in Gate 1. All 19 installer pins (7 replaced files,
12 dependencies) matched the live host, read only, before the build.

## Deployment (stop at the first line that does not match)

`alfred-dev-ops` reads the release from `/home/alfred/alfred-development-v1`, so after
merging, update that checkout to `main` as alfred (no root):

```bash
git -C /home/alfred/alfred-development-v1 switch main
```

```bash
git -C /home/alfred/alfred-development-v1 pull --ff-only
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 33
```

Type `e43215ab1b76` when asked. Expect `INSTALLED_HELD`, seven `OK` lines, the intake
restart, the role-sandbox preflight `"overall": "PASS"` and `"pause": "still set"`.

```bash
sudo alfred-dev-ops resume
```

Type `RESUME`. The next request for dev-v1-accept or demo-site sends no preview; the
owner's one text is the CTO plan, answered "yes".

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 33`.
