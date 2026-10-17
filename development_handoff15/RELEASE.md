# handoff.15 release pins and deployment procedure

Built by `development_handoff15/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.15` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.15.tar.gz` | `8dce2c89c0622015fa1fdd7cff286a097a5332a4b859d6c3d880dfee3bf6e826` |
| Release `MANIFEST.sha256` (18 payload files) | `5e59714481b47576272e2e7ea15d78a400b8054765f16b67b0ef63ffdae18cac` |
| Release `development_handoff15/install_patch.py` | `fdc0b886dd726d0ed3be1b3b51f0dba52cad2b89b3703eef6ed8fce53a27b58b` |

Staging evidence: Gate 1 passes, including `handoff15` (the fix-loop, installer,
team-skills and Independent QA suites). The 24 pins handoffs 13 and 14 do not touch
matched the live host; the rest are the exact bytes those releases install.

## Deployment (in this order; each installer refuses if an earlier one is missing)

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 13
```

Team skills: type `ce1f485370dc`.

```bash
sudo alfred-dev-ops install 14
```

The held-task fix: type `bf70707075ee`.

```bash
sudo alfred-dev-ops install 15
```

The fix loop: type `8dce2c89c062`. Expect `INSTALLED_HELD`, ten `OK` lines, the intake
restart, `"overall": "PASS"` and `"pause": "still set"`.

```bash
sudo alfred-dev-ops resume
```

Within about two minutes demo-site T-0001 starts. If QA or the Reviewer finds
problems the team fixes them (up to three rounds) before you hear anything. Your next
text is "Ready to publish", or after three failed rounds "I couldn't finish this one".

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 15`.
