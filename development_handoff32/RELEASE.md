# handoff.32 release pins and deployment procedure

Built by `development_handoff32/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.32` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.32.tar.gz` | `23bccead3063f6f46eb17562494320f4505355b0e2f6128914d9c1e0384bbdc9` |
| Release `MANIFEST.sha256` (11 payload files) | `8a34d32d9ef781d749644b090195e58b34b893bd7e2644d3f2b4882081e8404b` |
| Release `development_handoff32/install_patch.py` | `7a18a7e02c0c66cb849fdb0eea8725393b04a7fadd07d8db99c49b2dabb55c1d` |

Staging evidence (`staging-tests.xml`): 203 passed, 1 skipped (the explicit real-model
acceptance test), across the team-skills, handoff.32 transaction, Developer execution,
Developer, team snapshot, passkey approval, fresh V1 and Gateway adapter suites. All 12
installer pins (2 replaced files, 10 dependencies) matched the live host, read only,
before the build.

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
sudo alfred-dev-ops install 32
```

Type `23bccead3063` when asked. Expect `INSTALLED_HELD`, two `OK` lines, no restart, the
role-sandbox preflight `"overall": "PASS"` and `"pause": "still set"`.

```bash
sudo alfred-dev-ops resume
```

Type `RESUME`. Team skills reach specialists only once a CTO library snapshot exists:
deliver a merged hrsnyde1/alfred-team-skills commit with the library tool (its README,
"Delivering approved skills").

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 32`.
