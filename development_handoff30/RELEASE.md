# handoff.30 release pins and deployment procedure

Built by `development_handoff30/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.30` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.30.tar.gz` | `9e199771930af5ed54a47050f8f10d4e33886076b289962763e6387354788098` |
| Release `MANIFEST.sha256` | `64b86821dc3e10b8a22eb3d92caae1a20963f6c066c8cb16bafc48ff0cdfe58d` |
| Release `development_handoff30/install_patch.py` | `526d011923512c54da6ff7302a3d6fb707e44086e6c2961f4f913ad33f46d196` |

Staging evidence: Gate 1 passes, including `handoff30`. The T-0007 test fails on the
installed QA worker and passes on this one. All pins match the live host.

## Deployment

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 30
```

Type `9e199771930a`. Expect one `OK` line.

```bash
sudo alfred-dev-ops resume
```

Then send the header request again.
