# handoff.21 release pins and deployment procedure

Built by `development_handoff21/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.21` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.21.tar.gz` | `8113eb206e79a94664303e70b80f516869d4177121dea543f2bee820665d5000` |
| Release `MANIFEST.sha256` (15 payload files) | `5244435981c3f0adfd7e5e02527e0125bb85b71ddad88b42173396d65145b5a7` |
| Release `development_handoff21/install_patch.py` | `d4862ff70ce2e9fafaa6d4d994ff31c4192274d91ae347f7321f48ba39198f0b` |

Staging evidence: Gate 1 passes, including `handoff21`. Every pin matched the live
host (handoff.19 installed). It does not depend on handoff.20; install either first.
A live `claude -p` call through the new route, as the Frontend agent, returned a valid
edit.

## Deployment

**1. Install:**

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 21
```

Type `8113eb206e79`. Expect the `OK` lines and `"pause": "still set"`.

```bash
sudo systemctl daemon-reload
```

**2. Switch the agents to Claude** (as alfred, no sudo; keeps the old catalog beside it):

```bash
cp -p /var/lib/alfred-development-state/models.json /var/lib/alfred-development-state/models.codex-only.json
```

```bash
install -m 600 /home/alfred/alfred-development-v1/development_handoff21/models.json /var/lib/alfred-development-state/models.json
```

**3. Resume:**

```bash
sudo alfred-dev-ops resume
```

Then text Alfred a request for the demo site. The plan text is unchanged in this phase;
the developer report shows `"provider": "claude"`.
