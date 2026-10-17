# handoff.12 release pins and deployment procedure

Built by `development_handoff12/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.12` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.12.tar.gz` | `350cd830831b9cae6990f6b9a3777ad1b1e7b9123e155edb5cdfd5bc5264c751` |
| Release `MANIFEST.sha256` (18 payload files) | `f5fcfbfe5cfca9063234b4c37892438003592ed48b515f414160b6ccc5486755` |
| Release `development_handoff12/install_patch.py` | `32ba451a4c5b47273e7506b134998071c5c877966a22af4d472cd93a5d4ef13d` |

Staging evidence: Gate 1 passes all 16 suites, including `handoff12` (39 tests). All
22 byte pins matched the live host, read-only, before the build; the policy file is
checked by content at install time.

## Deployment (stop at the first line that does not match)

**1. Register the demo site** (as alfred, in a normal shell; the registry is yours):

```bash
cat ~/alfred-development-v1/development_handoff12/registry-demo-site.yaml >> ~/Git/alfred/registry/projects.yaml
```

**2. Let the Publisher push to the demo repo:** on GitHub, open the token used by
`/var/lib/alfred-draft-pr-private/github-token` (Settings, Developer settings,
Personal access tokens). If it is fine-grained, add repository
`hrsnyde1/alfred-demo-site` with Contents and Pull requests read/write. A classic
token with `repo` scope needs nothing.

**3. Install:**

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 12
```

Type `350cd830831b` when asked. Expect `INSTALLED_HELD`, eight `OK` lines, the intake
restart, `"overall": "PASS"` and `"pause": "still set"`.

```bash
sudo alfred-dev-ops resume
```

**4. Try it:** text Alfred

> Add a light/dark mode toggle to the demo site

Reply "yes" to the preview. Development is delegated, so the next text is "Ready to
publish"; reply "yes" in its thread, then "All done" arrives with the draft PR link.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 12`.
