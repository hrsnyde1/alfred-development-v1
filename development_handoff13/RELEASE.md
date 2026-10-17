# handoff.12 release pins and deployment procedure

Built by `development_handoff12/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.12` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md). The library side (snapshots, the Hermes
sync and their rollback) is `scripts/team_skills_deploy.py` in hrsnyde1/alfred-team-skills.

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.12.tar.gz` | `fc7419bdd1c175571e62423171919c80f5771342984915f94867ee52de5cb879` |
| Release `MANIFEST.sha256` (14 payload files) | `bc481a31dd129bcf9a0c44a725f16a5e6ade7f63e5f86c923c38a45ea6e2ad09` |
| Release `development_handoff12/install_patch.py` | `5329783a0d9a5c8fe5e4970e19fed1e9577850152bbb225ff5d14cfed4a6b9e8` |

Staging evidence (`staging-tests.xml`): 140 passed, 1 skipped, across the team-skills,
handoff.12 transaction, Developer, fresh V1, Gateway adapter, publication transaction,
host install, handoff.11 and CTO suites. All 20 installer pins (5 replaced files, 1 absent
new file, 14 dependencies) matched the live host, read only, before the build.

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
sudo alfred-dev-ops install 12
```

Type `fc7419bdd1c1` when asked. Expect `INSTALLED_HELD`, six `OK` lines, no restart, the
role-sandbox preflight `"overall": "PASS"` and `"pause": "still set"`.

```bash
sudo alfred-dev-ops resume
```

Type `RESUME`. Until a CTO snapshot exists, plans are unchanged. To turn team skills on,
deliver a merged library commit with the library tool (its README, "Delivering approved
skills"): `deploy.py cto --repo /root/alfred-team-skills/repo.git --commit <merge commit>`.
The next plan then carries `team_skills`.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 12`. Turning team skills
off without a rollback: `deploy.py cto-rollback --disable` in the library tool.
