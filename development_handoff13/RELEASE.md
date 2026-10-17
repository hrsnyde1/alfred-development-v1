# handoff.13 release pins and deployment procedure

Built by `development_handoff13/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.13` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md). The library side (snapshots, the Hermes
sync and their rollback) is `scripts/team_skills_deploy.py` in hrsnyde1/alfred-team-skills.

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.13.tar.gz` | `ce1f485370dc3384d271ee316562f4c4e4eca6557524769d265c724f11280306` |
| Release `MANIFEST.sha256` (14 payload files) | `d2991f593978bbf343e9ec4ca6036c7c9a1e45ce08d9652938fb77f11efc8e22` |
| Release `development_handoff13/install_patch.py` | `bf7e5fa3290a0a4e9cfcdde34ba1aec64a7c603bef268b036d634c4cdc6f9bfa` |

Staging evidence (`staging-tests.xml`): 179 passed, 1 skipped, across the team-skills,
handoff.13 transaction, Developer, fresh V1, Gateway adapter, publication transaction,
host install, handoff.11/12 and CTO suites. All 20 installer pins (5 replaced files, 1 absent
new file, 14 dependencies) matched the live host, with handoff.12 installed, read only, before
the build.

## Deployment (stop at the first line that does not match)

`alfred-dev-ops` reads the release from `/home/alfred/alfred-development-v1`, so after
merging, update that checkout to `main` as alfred (no root):

```bash
git -C /home/alfred/alfred-development-v1 switch main
```

```bash
git -C /home/alfred/alfred-development-v1 pull --ff-only
```

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 13
```

Type `ce1f485370dc` when asked. Expect `INSTALLED_HELD`, six `OK` lines, no restart, the
role-sandbox preflight `"overall": "PASS"` and `"pause": "still set"`.

```bash
sudo alfred-dev-ops resume
```

Type `RESUME`. Until a CTO snapshot exists, plans are unchanged. To turn team skills on,
deliver a merged library commit with the library tool (its README, "Delivering approved
skills"): `deploy.py cto --repo /root/alfred-team-skills/repo.git --commit <merge commit>`.
The next plan then carries `team_skills`.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 13`. Turning team skills
off without a rollback: `deploy.py cto-rollback --disable` in the library tool.
