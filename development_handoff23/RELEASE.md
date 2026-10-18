# handoff.23 release pins and deployment procedure

A slow Photon acknowledgement no longer fails a delivered completion (see
[HOST.md](HOST.md)). Built by `development_handoff23/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.23` rebuilds it byte for byte. It
installs one file, `completion_integration/runtime.py`.

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.23.tar.gz` | `51cacd0f4f5f6caf14386a3cc63af79eb884f2e31fd597d1d3119177da0a3851` |
| Release `MANIFEST.sha256` (10 payload files) | `658aa9c403ba4e60174467f6dd28070a109ae4b8d68b71124457a08d9ddb2c90` |
| Release `development_handoff23/install_patch.py` | `040b0c18e9d3c4efc5b157d3e25cf01f70a47031e9e8f141f46db764d0a1f9e2` |
| Installed `runtime.py` after | `d34fad6928b5a6b7508678887e49ce9d6fc4cd2ddfb18382ba70be26f0207c61` |

Staging evidence: Gate 1 passes, including `handoff23`. Every readable pin (35 of 36)
matched the live host with handoff.22 installed; the root-only `policy.json` pin is
unchanged from handoff.22.

## Deployment

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 23
```

Type `51cacd0f4f5f`. Expect one `OK` line and `"pause": "still set"`.

```bash
sudo alfred-dev-ops resume
```

demo-site/T-0003 and dev-v1-accept/T-0002 stay held after this install: their
completion records remain `uncertain` by design (see HOST.md, "Not changed").
