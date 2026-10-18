# handoff.29 release pins and deployment procedure

Built by `development_handoff29/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.29` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.29.tar.gz` | `d9541667f7fb74890385de0f8aa523734104525abafdfb15a32a55688232ce47` |
| Release `MANIFEST.sha256` | `0bf4016257c1fe409de06632c0fc2ee13162d28d40650c173a7c96685f5ad8bf` |
| Release `development_handoff29/install_patch.py` | `8a6e2136ff1db772be1daec21c619f9ae9a18f02c6b8d3a4f8760d62429c2df2` |

Staging evidence: Gate 1 passes, including `handoff29` (74 tests: the one-yes flow end
to end, owner policy and unlisted projects still asking, delegation turned off before
publishing, a tampered delegated record, wording). All 10 pins match the live host.

## Deployment

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 29
```

Type `d9541667f7fb`. Expect seven `OK` lines; the intake restarts. Expect
`"pause": "still set"`.

```bash
sudo alfred-dev-ops resume
```
