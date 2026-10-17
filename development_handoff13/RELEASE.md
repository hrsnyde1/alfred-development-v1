# handoff.13 release pins and deployment procedure

Built by `development_handoff13/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.13` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.13.tar.gz` | `70d856db9ecda65c425decea44c6c7a1d6857dedd6494a7bde2a2adcf5167a5f` |
| Release `MANIFEST.sha256` (10 payload files) | `17c03c0c7b09f9eba8302325410017ff89ef4102279f74385b5bdac4d9815594` |
| Release `development_handoff13/install_patch.py` | `01ad0dfcf3649a2ad9a90fd6d5e46bf54714eb2ad13e14b0ca3627a32bcf64af` |

Staging evidence: Gate 1 passes all 17 suites. The existing test that an uncertain
attempt still blocks everything after it passes unchanged; only holds after a
recorded verdict are moved past. 21 readable pins matched the live host; the
root-only policy is pinned to the exact bytes handoff.12 installed.

## Deployment

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 13
```

Type `70d856db9ecd` when asked. Expect `INSTALLED_HELD`, one `OK` line,
`"overall": "PASS"` and `"pause": "still set"`. No service restarts.

```bash
sudo alfred-dev-ops resume
```

Within about two minutes demo-site T-0001 starts. The next text you get is
"Ready to publish" (development is delegated for the demo site).

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 13`.
