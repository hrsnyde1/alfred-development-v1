# handoff.35 release pins and deployment procedure

Built by `development_handoff35/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.35` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.35.tar.gz` | `8b51f49e3ab31f3c5a1722adf6768048471e8273fed1923930c8492990902977` |
| Release `MANIFEST.sha256` | `9731f00c54d9dab75805ada00f3ff16d18f84d173f8be385e2762b36b3a25e96` |
| Release `development_handoff35/install_patch.py` | `2e9fff7bd55d72610339a4b0bf3262b321384b891186ba9c8c1ea92650b6b355` |

Staging evidence: Gate 1 passes, including `handoff35` (88 tests). Three of four pins
match the live host. The fourth is handoff.34's `repo_intelligence.py`, which matches
once handoff.34 is installed. The CTO identity from alfred-team-skills PR #11 builds at
8,833 bytes with `Escalation.md` (cap 12,288).

## Deployment
Install handoff.34 first (PR #39).

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 35
```

Type `8b51f49e3ab3`. Expect two `OK` lines.

```bash
sudo alfred-dev-ops resume
```
