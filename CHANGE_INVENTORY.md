# v0.1.4 corrective workspace inventory — no release built

The following existing files differ from the immutable v0.1.3 archive
(SHA-256 comparison of its members with the workspace). The v0.1.2 and
v0.1.3 archives passed their recorded outer SHA-256 checks.

```text
CHANGE_INVENTORY.md
INDEPENDENT_REVIEW_RESPONSE.md
INDEPENDENT_SECURITY_REVIEW.md
MIGRATION_RECOVERY.md
PHOTON_SECURITY_ARCHITECTURE.md
README.md
TEST_RESULTS.md
THREAT_MODEL.md
make_photon_patch.py
patches/photon-durable-spool.mjs.txt
patches/photon-secure-front.proposed.patch
task_a/audit.py
task_a/durable.py
task_a/front_runner.py
task_a/photon_front.py
task_a/service.py
task_a/transport.py
tests/test_broker_transport.py
tests/test_durable.py
tests/test_photon_front.py
tests/test_reply_binding.py
tests/test_sidecar_spool.py
```

New file: `V014_CORRECTIVE_STATUS.md`. Local unarchived virtual environment
and package-cache directories were created inside Task A during the failed
offline dependency installation. No v0.1.4 archive or payload manifest was
created because the corrections and acceptance gates are incomplete.

## Historical v0.1.3 payload changes relative to immutable v0.1.2

Compared byte-for-byte by SHA-256 with
`dist/alfred-task-a-staging-0.1.2.tar.gz`. The v0.1.2 archive and checksum
were not changed.

## Changed files

```text
ATTACHMENT_COMPATIBILITY.md
INDEPENDENT_SECURITY_REVIEW.md
MIGRATION_RECOVERY.md
PHOTON_SECURITY_ARCHITECTURE.md
README.md
TEST_RESULTS.md
build_release.py
make_photon_patch.py
patches/photon-secure-front.proposed.patch
task_a/front_runner.py
task_a/photon_front.py
task_a/transport.py
templates/permissions/paths.json
templates/systemd/alfred-photon-intake.service
tests/test_broker_transport.py
tests/test_photon_front.py
tests/test_photon_patch.py
tests/test_release.py
```

## New files

```text
CHANGE_INVENTORY.md
INDEPENDENT_REVIEW_RESPONSE.md
THREAT_MODEL.md
patches/photon-durable-spool.mjs.txt
task_a/audit.py
task_a/durable.py
task_a/service.py
tests/test_durable.py
tests/test_reply_binding.py
tests/test_service.py
tests/test_sidecar_spool.py
```

No v0.1.2 payload file was removed. The unarchived
`dist/RELEASE_STATUS.txt` is updated separately when the v0.1.3 archive is
built and verified.
