# handoff.14 release pins and deployment procedure

Built by `development_handoff14/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.14` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md). This is the change first proposed as a
second "handoff.13" (PR 16); it was renumbered because handoff.13 is team skills (PR 15).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.14.tar.gz` | `bf70707075ee75d2ba1e7ee63c02f2c3b6b8c3d6d5f400dc693386c268c410f7` |
| Release `MANIFEST.sha256` (10 payload files) | `20624ba3c648e4342d75f4075c3da968455c95c3c87534678e31de655da25955` |
| Release `development_handoff14/install_patch.py` | `80b07853778cf69bc9b71a5ee4e3b4c59fc177f33de3a0d65856ff7d552bb991` |

Staging evidence: Gate 1 passes; the team-skills tests (handoff.13) pass against this
`host.py`. The base pin is the live handoff.12 `host.py`. The files handoff.13 replaces
are not pinned, so the two install in either order, except that handoff.13 itself pins
the handoff.12 `host.py`: install handoff.13 first if you want both.

## Deployment

```bash
sudo alfred-dev-ops pause
```

Optional, team skills first (see `development_handoff13/RELEASE.md`; type `ce1f485370dc`):

```bash
sudo alfred-dev-ops install 13
```

Then this fix (type `bf70707075ee`):

```bash
sudo alfred-dev-ops install 14
```

Expect `INSTALLED_HELD`, one `OK` line, `"overall": "PASS"` and `"pause": "still set"`.
No service restarts.

```bash
sudo alfred-dev-ops resume
```

Within about two minutes demo-site T-0001 starts. The next text is "Ready to publish".

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 14`.
