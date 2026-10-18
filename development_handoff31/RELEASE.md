# handoff.31 release pins and deployment procedure

Built by `development_handoff31/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.31` rebuilds it byte for byte. The why
and how, and what the owner must check first, are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.31.tar.gz` | `024ac068e26b68b673fabb8ddfdc37c921701f4f9dbae19c402bb857ab31bef8` |
| Release `MANIFEST.sha256` | `62859364192bc43fa905280bed784c25f6b11e3d1653c5a3b1fe7f45289ed255` |
| Release `development_handoff31/install_patch.py` | `adaf4ac9654054ee0b550056dccb14c4f0f406b000b8a5901c209b4867d62e51` |

Staging evidence: Gate 1 passes, including `handoff31` (123 tests: one yes to a squash
merge on a real Git remote, the owner policy and an unlisted draft-PR policy still not
merging, main moved and GitHub refusing (nothing merged, owner told), no answer from
GitHub never assumed, "undo" reverting exactly the squash commit, keeping later unrelated
changes, refusing a clashing undo, only the owner's own native reply within 24 hours,
QA's copy of the policy check, the squad chat). All 20 pins match the live host, except
QA's worker, which is pinned at handoff.30's installed bytes.

## Deployment

Install handoff.30 first (`sudo alfred-dev-ops install 30`); this release refuses
otherwise and changes nothing. Then check the two GitHub items in HOST.md.

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 31
```

Type `024ac068e26b`. Expect fifteen `OK` lines; the intake restarts. Expect
`"pause": "still set"`.

```bash
sudo alfred-dev-ops resume
```
