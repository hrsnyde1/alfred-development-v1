# handoff.22 release pins and deployment procedure

handoff.20 repackaged to install after handoff.21 (see [HOST.md](HOST.md)). Built by
`development_handoff22/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.22` rebuilds it byte for byte. Its three
installed files are byte-identical to handoff.20's.

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.22.tar.gz` | `7cc533a84c7fa6e1ff21210a45e106ad18bbd88cb1161c518e4a3d30ff99bad7` |
| Release `MANIFEST.sha256` (12 payload files) | `2ae3fd9970002ce92839b44ef9bafccae608e39664003a9f91608802fd3d64d2` |
| Release `development_handoff22/install_patch.py` | `0752541927193e50c8a31740ea01a8d8ce425ee8ee18c828931ae11eb58cc871` |

Staging evidence: Gate 1 passes, including `handoff22`. Every readable pin (33 of 34)
matched the live host with handoff.21 installed.

## Deployment

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 22
```

Type `7cc533a84c7f`. Expect three `OK` lines and `"pause": "still set"`.

```bash
sudo alfred-dev-ops republish demo-site/T-0003
```

```bash
sudo alfred-dev-ops resume
```
