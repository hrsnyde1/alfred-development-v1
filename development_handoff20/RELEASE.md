# handoff.20 release pins and deployment procedure

Built by `development_handoff20/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.20` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.20.tar.gz` | `643e0901d90cd5fbd7af465beb8341697150042fa68cf080ba37050daba7c490` |
| Release `MANIFEST.sha256` (12 payload files) | `3436df56f970b5b6f1e3cdbe160949d8fd4d26cf9e4fbcb5883d8bcb29158e57` |
| Release `development_handoff20/install_patch.py` | `0160bda603665b50c25ded638804688f3d07a506220676d35f4720fff2135309` |

Staging evidence: Gate 1 passes, including `handoff20`. All 30 readable pins matched the
live host (with handoff.19 installed), owner, mode, links and hash.

## Deployment

**1. GitHub (in your browser):** give the Publisher's token access to
`hrsnyde1/alfred-demo-site`, with Contents and Pull requests set to read and write.

**2. Install and retry T-0003:**

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 20
```

Type `643e0901d90c`. Expect three `OK` lines and `"pause": "still set"`.

```bash
sudo alfred-dev-ops republish demo-site/T-0003
```

Expect `"retry": 1`.

```bash
sudo alfred-dev-ops resume
```

Within about two minutes: "All done with demo-site. It's on GitHub as a draft for your
review." plus the link. If the token still cannot see the repository, the retry reports
the same 404; fix the token and run `republish` again (up to three retries).

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 20`.
