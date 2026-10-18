# handoff.26 release pins and deployment procedure

Built by `development_handoff26/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.26` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.26.tar.gz` | `b193bc459a7fce4f7b393d969bfa271f1ca4ef6475f4f4106c0273a7b46955c7` |
| Release `MANIFEST.sha256` (12 payload files) | `d430db993b67c1e5efa4d1ffdd8db98b41f5eb4384dd20d1fad540edf1c88af4` |
| Release `development_handoff26/install_patch.py` | `79e12505f5d724b495e4bb8a0cfb0c1e96722acaf2a6cbed96a21be90365a563` |

Staging evidence: Gate 1 passes, including `handoff23` and `handoff26`. 12 of 13 pins
match the live host. The 13th is handoff.23's `runtime.py`, which matches once
handoff.23 is installed. In a sandbox with `/home` read-only, the new route wrote only
to its private home, and a rejected token came back as "unavailable" (the Codex
fallback path).

## Deployment

**1. Create the agents' token** (as alfred, in a terminal; it opens a browser sign-in
and prints a token valid for one year):

```bash
claude setup-token
```

Copy the token it prints.

**2. Install handoff.23, then handoff.26, and save the token:**

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 23
```

Type `51cacd0f4f5f`.

```bash
sudo alfred-dev-ops install 26
```

Type `b193bc459a7f`. Expect three `OK` lines and `"pause": "still set"`.

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
