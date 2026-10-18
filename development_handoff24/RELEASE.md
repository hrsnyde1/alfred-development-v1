# handoff.24 release pins and deployment procedure

The owner can confirm a completion text they received although its delivery record
stayed `uncertain` (see [HOST.md](HOST.md)). Built by
`development_handoff24/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.24` rebuilds it byte for byte. It installs
two files: `development_handoff24/host.py` (the installed host.py plus this fix, without
main's unreleased team-snapshot changes) and `ops/alfred_dev_ops.py` (handoff.26's, plus
`confirm-delivered`).

**Install order: 23, then 26, then 24.** This release pins handoff.23's `runtime.py` and
handoff.26's `alfred-dev-ops`, `real_worker.py` and `60-claude-agents.conf`. Until both
are installed, the installer refuses before changing anything.

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.24.tar.gz` | `f6321172711c23d798a73b639b692a76fd09cd3fb879375f4f9b36b33fb0fd03` |
| Release `MANIFEST.sha256` (11 payload files) | `e6d8557518119677c595de907c0f2a0994c0075738103d196aa9d9e17386bea3` |
| Release `development_handoff24/install_patch.py` | `81a335cca92e3fd9936acb5af4479d9b63bd1c5f720643313f59d94ae16793a5` |
| Installed `host.py` after | `7c67a3234fa11d85950c1d5a6747845e327f469723870a594b44cf065909bf87` |
| Installed `alfred-dev-ops` after | `9514cbdbc71be70585b097bdae0454c86eed786583e5c6a495adaa672f0076a4` |

Staging evidence: Gate 1 passes, including `handoff24`. The live host was read on 2026-10-18 with handoffs 23 and 26 installed: all 35 readable pins matched it, and the root-only `policy.json` pin is unchanged.

## Deployment

After `install 23` and `install 26` (see their RELEASE.md files):

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 24
```

Type `f6321172711c`. Expect one `OK` line for each of the two files and
`"pause": "still set"`.

```bash
sudo alfred-dev-ops confirm-delivered demo-site/T-0003
```

Type `RECEIVED`. Expect `"state": "owner-confirmed received"` and
`"transport_state": "uncertain"`. Nothing is sent.

```bash
sudo alfred-dev-ops resume
```

The next poll writes demo-site/T-0003's `complete.json`
(`"notification": "owner_confirmed_received"`). dev-v1-accept/T-0002 needs nothing: it
has no fresh V1 task directory and was already reconciled on 2026-10-16 (see HOST.md,
"Known cases").
