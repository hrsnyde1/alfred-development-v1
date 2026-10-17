# Public source export

This repository contains the complete reviewed Development V1 staging source,
tests, documentation, configuration examples, historical code candidates and
audited release archives. The original Development Lab and protected production
artifacts are unchanged.

## Exclusions

Local tool configuration, credentials, dependency installations, Python/Node caches,
bundled Node binaries and Photon payload bundles containing those dependencies are
not included. Canonical live acceptance task records under `live-acceptance/repo/.dev/`
and an accidental local terminal-output capture are also excluded. Protected live
grants, owner decision records and private runtime configuration outside the Lab
were never copied. Static example/fixture task definitions remain available in the
source and release packages.

## Privacy edit

Only the public copy of `v1_1b/staging/sidecar/index.mjs` replaces a hardcoded private
probe destination with the fictional `+15550100100`. The original staging file
is unchanged. Real use requires explicitly configured authorized routing.
Release archives and their pinned manifests are byte-for-byte copies and have not
been rebuilt. The root README is an updated navigation/status page; the original
is preserved under `docs/history/`.

## Integrity and checks

`PUBLIC_SOURCE.sha256` inventories all exported files except itself and Git metadata.
Run `sha256sum -c PUBLIC_SOURCE.sha256` from the repository root. Before publication,
text files and text members of every included tar archive were checked for common
credential signatures and phone/email references. Matches were reviewed as fixtures,
examples or systemd unit names, apart from the private probe destination edited above.
This is a scoped check, not a guarantee that a scanner can detect every possible
secret.

The latest focused continuation/ownership-contract tests passed 33 cases in the
Development Lab. No production deployment, service restart or live acceptance was
performed for this upload.

## Historical host-test limitation

An additional attempt to run `tests/test_photon_dm_resolution_patch.py` stopped
at its historical installed-sidecar checksum assertion: it requires the old
pre-fix hash, while this host already has the corrected Photon source. No send
or protocol exercise ran. That test is retained as historical migration evidence;
this upload does not claim a fully passing portable suite. The privacy-edited
public sidecar passed Node syntax validation without executing it.
