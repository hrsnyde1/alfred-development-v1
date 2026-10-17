# handoff.8 release pins and root commands

Staging review artifact. Built by `development_handoff8/build_release.py`;
`--reproduce dist/alfred-fresh-v1-1.0.1-development-handoff.8` rebuilds it byte for
byte. The why and how are in [HOST.md](HOST.md).

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.8.tar.gz` | `85d11b339245e2df17d8233f1ed09e8c1e12d2e390fecde2fa58e72ac699838a` |
| Release `MANIFEST.sha256` (15 payload files) | `0f81d7c094b02874c1a719db37aa8009ed6ab702ee203c2269867a5e9194a6c4` |
| Release `development_handoff8/install_patch.py` | `1e35a2beed917e32ba0c3562a975dd39defd46cc5d5ab9e2e25e88fb03dbcdec` |
| Release `ops/alfred_dev_ops.py` (the helper) | `3c4d70877793358f403092fc5f06a2b4ea70103a21bbf830dc017cc2b69c223b` |

Staging evidence: Gate 1 passes all 12 suites, including the new `handoff8` suite
(delegation, installer, Independent QA evidence, ops helper).

## Root commands

**Do handoff.7 first** ([its RELEASE.md](../development_handoff7/RELEASE.md), commands
1 and 2 only; keep PAUSE set). Then, in the same root shell (`sudo -i`), stop at
the first line that does not match:

**1. Install the operations helper from the verified archive (one time):**

```bash
A=/home/alfred/alfred-development-v1/dist/alfred-fresh-v1-1.0.1-development-handoff.8.tar.gz; B=/root/alfred-dev-ops-bootstrap; echo "85d11b339245e2df17d8233f1ed09e8c1e12d2e390fecde2fa58e72ac699838a  $A" | sha256sum -c - && install -d -m 0700 $B && tar --no-same-owner --no-same-permissions -xzf $A -C $B && install -o root -g root -m 0755 $B/alfred-fresh-v1-1.0.1-development-handoff.8/ops/alfred_dev_ops.py /usr/local/sbin/alfred-dev-ops && echo "3c4d70877793358f403092fc5f06a2b4ea70103a21bbf830dc017cc2b69c223b  /usr/local/sbin/alfred-dev-ops" | sha256sum -c -
```

Expect two `OK` lines.

**2. Install handoff.8 with the helper:**

```bash
alfred-dev-ops install 8
```

When asked, type `85d11b339245`. Expect `INSTALLED_HELD`, one `OK` per installed
file, the intake restart, `"overall": "PASS"` from the preflight, and finally
`"pause": "still set"`.

**3. Turn on delegation for the test project:**

```bash
install -o root -g root -m 0644 /root/alfred-dev-ops-bootstrap/alfred-fresh-v1-1.0.1-development-handoff.8/ops/delegation.example.json /etc/alfred-development/delegation.json
```

**4. Resume and test (T-0009):**

```bash
alfred-dev-ops resume
```

Type `RESUME`. Then text Alfred a small request for the test project and confirm
it. Development now starts without an approval text. You still get the
publication approval text: reply in the thread, and the draft PR link follows.

## Turning it off
- Stop delegation: `rm /etc/alfred-development/delegation.json`. Approvals come to
  your phone again, and delegated grants that have not run are refused.
- Undo handoff.8: `alfred-dev-ops pause`, then `alfred-dev-ops rollback 8`.
- Audit: `cat /var/log/alfred-dev-ops.jsonl`.
