# handoff.19 release pins and deployment procedure

Built by `development_handoff19/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.19` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.19.tar.gz` | `d6c2e225cba858033a4ef4463447a03216c56da5a479f805a29c25c55e800913` |
| Release `MANIFEST.sha256` (12 payload files) | `824f6e8ffe221b8d5c55a5e2811ef5ed00873f7f71087518a53c752a01790470` |
| Release `development_handoff19/install_patch.py` | `c59b793e874974e2ff2b783d3908745cd654cc24cd84a24516880ef1e201375b` |

Staging evidence: Gate 1 passes, including `handoff19`. The plain-request test fails on
the previous `role.py` (it reproduces T-0002's QA rejection) and passes with this one.
All 30 readable pins were dry-run against the live host (owner, mode, links, hash) with
no refusals; the root-only policy is pinned to the bytes handoff.12 installed.

## Deployment

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 19
```

Type `d6c2e225cba8`. Expect three `OK` lines, `"overall": "PASS"` and
`"pause": "still set"`. Nothing restarts.

```bash
sudo alfred-dev-ops abandon demo-site/T-0002
```

Expect `"state": "abandoned"`. (T-0002's QA stage was left unrecorded by the old host;
this stops it for good without changing its evidence, so later requests can run.)

```bash
sudo alfred-dev-ops resume
```

Then send the request again from your phone: "Add a light/dark mode toggle to the demo
site". Reply yes to the preview.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 19`.
