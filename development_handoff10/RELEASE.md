# handoff.10 release pins and deployment procedure

Built by `development_handoff10/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.10` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.10.tar.gz` | `a617c5a8ff309cf280fa8649fb8923c409761295b0a068cfba16d9974d0f6142` |
| Release `MANIFEST.sha256` (14 payload files) | `899e22461544e348ef99f2985f853c8a09095ee4020bf66daec46c15e3e16678` |
| Release `development_handoff10/install_patch.py` | `5846d2783795144d63e97806e30ce691d516f8c7515873953d6d6c209b3fb973` |

Staging evidence: Gate 1 passes all 14 suites, including `handoff10` (61 tests:
gate, Publisher, schema, approval text, end-to-end and installer). All 17 installer
pins matched the live host, read-only, before the build.

## Deployment (root, stop at the first line that does not match)

**1. Pause:**

```bash
sudo alfred-dev-ops pause
```

**2. Install,** typing `a617c5a8ff30` when asked:

```bash
sudo alfred-dev-ops install 10
```

Expect `INSTALLED_HELD`, four `OK` lines, the intake restart, `"overall": "PASS"`
and `"pause": "still set"`.

**3. Verify T-0009 without changing it (read-only):**

```bash
sudo /usr/bin/python3 -I -B /root/alfred-fresh-v1-1.0.1-development-handoff.10-review/alfred-fresh-v1-1.0.1-development-handoff.10/development_handoff10/verify_t0009.py
```

Expect `"verdict": "WILL_ADVANCE_TO_PUBLICATION_PREPARATION"`,
`"reviewer_result_unchanged": true`, `"recorded_failures": []`,
`"publication_started": false`, and every finding with severity `info`. If the verdict
is `HELD`, stop and send the output: T-0009 has a real blocking condition.

**4. Resume,** typing `RESUME`:

```bash
sudo alfred-dev-ops resume
```

Within about two minutes, you should receive T-0009's **publication approval** text,
which now lists the Reviewer's informational notes. Reply in that thread with the
exact phrase to create the draft PR. Nothing merges or deploys.

## Rollback
`sudo alfred-dev-ops pause`, then `sudo alfred-dev-ops rollback 10`.
