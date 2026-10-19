# handoff.36 release pins and deployment procedure

Built by `development_handoff36/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.36` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.36.tar.gz` | `801479181a54cdb5f550bf44cbac01a3fb2bca0b0c410c8746ad9361dd7c5e75` |
| Release `MANIFEST.sha256` | `82c704d14ce08682051384e8013c0810ad886c238b3b94a278afafc2223f5c8f` |
| Release `development_handoff36/install_patch.py` | `ea731ebae1be0691e9482182594e18a6ec9ba010d9e1b5959e56332456241b2a` |

Staging evidence: Gate 1 passes in full, including `handoff36` (154 tests) and
`handoff-selection` (204 tests). `staging-tests.xml` holds 199 targeted tests. All four
pins match the live host on 2026-10-19: both files replaced, handoff.35's
`team_snapshot.py` and `upgrade.py`. The bundle reproduces exactly from alfred-team-skills
`3f89e281`, and the same script reproduces handoff.21's bundle from `59836a2`.

This branch also corrects `developer_v1/release.sha256` for `agent_profiles.py`. PR #41
changed that file without updating the manifest, so `main` failed 7 `test_host_install_v1`
tests.

## Deployment
Merge alfred-team-skills #25 first, with a merge commit (see HOST.md).

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 36
```

Type `801479181a54`. Expect two `OK` lines.

```bash
sudo alfred-dev-ops resume
```

## Rollback

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops rollback 36
```
