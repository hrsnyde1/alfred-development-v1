# handoff.23 release pins and deployment procedure

Built by `development_handoff23/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.23` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.23.tar.gz` | `213fd398fed8c9e381933b508b156666665b7d2d68256da101e784473c9a21eb` |
| Release `MANIFEST.sha256` (12 payload files) | `d9238598a1be4139e775d5ac1a24a4f403c68ec72866780f4aef2ada63782c3f` |
| Release `development_handoff23/install_patch.py` | `bd85ff7a0be61de1f98fa3a7099ccead0d2dd43689b3c8596f542b7c9fc5bc1a` |

Staging evidence: Gate 1 passes, including `handoff23`. All 12 pins matched the live
host (handoffs 21 and 22 installed). In a sandbox with `/home` read-only, the new route
wrote only to its private home, and a rejected token came back as "unavailable" (the
Codex fallback path).

## Deployment

**1. Create the agents' token** (as alfred, in a terminal; it opens a browser sign-in
and prints a token, valid one year):

```bash
claude setup-token
```

Copy the token it prints.

**2. Install and save the token:**

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 23
```

Type `213fd398fed8`. Expect three `OK` lines and `"pause": "still set"`.

```bash
sudo systemctl daemon-reload
```

```bash
sudo alfred-dev-ops claude-token
```

Paste the token (nothing shows while you paste) and press Enter. Expect
`"claude_token": "saved"` and a fingerprint.

```bash
sudo alfred-dev-ops resume
```

Then text Alfred the footer request again.
