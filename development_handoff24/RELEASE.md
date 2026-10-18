# handoff.24 release pins and deployment procedure

The owner can confirm a completion text they received although its delivery record
stayed `uncertain` (see [HOST.md](HOST.md)). Built by
`development_handoff24/build_release.py`; `--reproduce
dist/alfred-fresh-v1-1.0.1-development-handoff.24` rebuilds it byte for byte. It installs
two files, `fresh_v1/host.py` and `ops/alfred_dev_ops.py`.

| Artifact | SHA-256 |
| --- | --- |
| `dist/alfred-fresh-v1-1.0.1-development-handoff.24.tar.gz` | `3dd2791bb7fdb13941f6abfc12616a655bda679ed5bf181a6e015a52d17cec50` |
| Release `MANIFEST.sha256` (11 payload files) | `4ad921f0bd2099a8517ebf939a4dcdd2b852dbe49d7559ead138c8d17463ea62` |
| Release `development_handoff24/install_patch.py` | `50853a125c54d9ef23c44a5b3f733a129720e54fe59e78dc59749636711f27d0` |
| Installed `host.py` after | `7c67a3234fa11d85950c1d5a6747845e327f469723870a594b44cf065909bf87` |
| Installed `alfred-dev-ops` after | `0bdcd427a858a1921db2444ace1c6a77b23cdd3b203b3c72e0d6fe45870f976d` |

Staging evidence: Gate 1 passes, including `handoff24`. The live host (handoff.22
installed) was read on 2026-10-18. 34 of the 36 pins matched it; the root-only
`policy.json` pin is unchanged. The one other mismatch is `completion_integration/runtime.py`:
it is still at its pre-handoff.23 bytes. This release requires handoff.23's runtime.py, so
**install handoff.23 first**. Until then the installer refuses before changing anything.

## Deployment

After `sudo alfred-dev-ops install 23` (see `development_handoff23/RELEASE.md`):

```bash
sudo alfred-dev-ops pause
```

```bash
sudo alfred-dev-ops install 24
```

Type `3dd2791bb7fd`. Expect one `OK` line for each of the two files and
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
