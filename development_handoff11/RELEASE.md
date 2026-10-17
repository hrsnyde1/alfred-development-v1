# handoff.11 release pins and deployment procedure

Built by `development_handoff11/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.11` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.11.tar.gz` | `adb88539cbde5690ae09caf970c28ea7a649ee29c1d30a2bbe5ce6923ae49dd7` |
| Release `MANIFEST.sha256` (15 payload files) | `43bade1ad98ae1a842f3d7a4862d612fbd04a9aadb6c661dd2a0bc3d875409f1` |
| Release `development_handoff11/install_patch.py` | `5bb694c0ca69f7691306a8c9c4b4cb13d0182d5927398d77388a98a51db00209` |

Staging evidence: Gate 1 passes all 15 suites, including `handoff11` (83 tests). All
19 installer pins matched the live host, read-only, before the build.

## Deployment (stop at the first line that does not match)

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 11
```

Type `adb88539cbde` when asked. Expect `INSTALLED_HELD`, seven `OK` lines, the intake
restart, `"overall": "PASS"` and `"pause": "still set"`.

```bash
sudo alfred-dev-ops resend T-0009
```

Expect `"resend": 1`. (T-0009's old 5-minute approval expired unanswered; this asks
for one fresh, plain-language one.)

```bash
sudo alfred-dev-ops resume
```

Type `RESUME`. Within about two minutes you get "Ready to publish: … Reply "yes" to
this message". Press and hold it, tap Reply, send `yes`. A few minutes later:
"All done with dev-v1-accept. It's on GitHub as a draft for your review." plus the
link. Hermes may still comment on the approval text in its own words; ignore it,
Hermes does not decide approvals.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 11`.
