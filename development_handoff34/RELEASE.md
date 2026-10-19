# handoff.34 release pins and deployment procedure

Built by `development_handoff34/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.34` rebuilds it byte for byte. The why
and how are in [HOST.md](HOST.md); the format in
[docs/REPO_INTELLIGENCE.md](../docs/REPO_INTELLIGENCE.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.34.tar.gz` | `6cbd697e7251d40c7068796ef9780842aa91b8be872ebbb3741809ab811f1353` |
| Release `MANIFEST.sha256` (18 payload files) | `3a886bc44d6bab0c7ea15201fc2e25f08ad2285b2717ae12058b3247f8107802` |
| Release `development_handoff34/install_patch.py` | `3a39bac067309352c2441c2e574b1eff87ab75443a96fae8ea41750f95c2f028` |

Staging evidence (`staging-tests.xml`): 252 passed, 1 skipped (the explicit real-model
acceptance test), across the Repo Intelligence, handoff.34 transaction, fresh V1, team
snapshot, team skills, Claude agents, fix loop, Developer execution, model message
contract, plan approval, one-yes and independent QA suites. One upgrade test (the
installed-after pins against the built tree) can only run after the build; it passes in
Gate 1. All 19 installer pins (3 replaced files, 16 dependencies) matched the live host,
read only, before the build, and the 5 new files do not exist yet.

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
sudo alfred-dev-ops install 34
```

Type `6cbd697e7251` when asked. Expect `INSTALLED_HELD`, eight `OK` lines, no restart,
the role-sandbox preflight `"overall": "PASS"` and `"pause": "still set"`.

```bash
sudo systemctl daemon-reload
```

```bash
sudo systemctl enable --now alfred-repo-intelligence.timer
```

Optionally profile the repositories right away instead of waiting 2 minutes:

```bash
sudo systemctl start alfred-repo-intelligence.service
```

Expect `"status": "refreshed"` with a commit for `demo-site/site` and `dev-v1-accept/app`
in `journalctl -u alfred-repo-intelligence.service`, and
`/var/lib/alfred-repo-intelligence/demo-site/profile.md`.

```bash
sudo alfred-dev-ops resume
```

Type `RESUME`. The next plan for dev-v1-accept or demo-site carries the Repo
Intelligence block in its planning note; the texts the owner gets are unchanged.

## Rollback
`sudo systemctl disable --now alfred-repo-intelligence.timer`, `sudo alfred-dev-ops pause`,
`sudo alfred-dev-ops rollback 34`, then `sudo systemctl daemon-reload`.
