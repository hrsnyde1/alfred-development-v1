# Publisher V1.1.0 staging results

Readiness: **PASS for operator installation**. Production has not been changed.

The supplied live diagnostic under `alfredpublish` UID 981 established that
bare initialization passed, local fetch failed with exit 128 and unsafe source
ownership, and fetch with temporary exact source trust passed. The installed
V1 worker matches the inspected original hash
`88eace873994d080000ed0ef12d25107e63223b3fbcf1253e22450e25fde7f76`.
Its isolated fetch disabled system/global Git configuration and supplied no
ownership exception for the protected root-owned source. Local upload-pack
therefore refused the source before GitHub push.

The only runtime change is in `draft_pr_publisher/worker.py:358`:
create a mode 0600 config inside the private temporary repository containing
one canonical source `safe.directory`, and set `GIT_CONFIG_GLOBAL` to that file
only for the fetch subprocess. This also reaches the local upload-pack child;
a parent `git -c` setting alone does not. Init and push retain their previous
environment. Temporary cleanup removes the config. Wildcard source trust is
rejected, and config creation failure stops publication.

## Verification

```sh
python3 -m unittest discover -s tests -p test_draft_pr_publisher.py -v
python3 -m unittest discover -s tests -p test_publisher_upgrade_procedure.py -v
```

| Check | Result |
| --- | --- |
| Full Publisher evidence, plan, authorization, Git, draft, and retry suite | 25 tests PASS |
| Documented upgrade, rollback, and bad-handoff suite | 3 tests PASS |
| Original local fetch with ownership mismatch | Reproduced exit 128, dubious ownership |
| Corrected local fetch with ownership mismatch | PASS |
| Unrelated repository with the fetch environment | Rejected, exit 128 |
| Exact source trust scope, config mode and cleanup | PASS |
| Source file hashes and modes before/after corrected fetch | Identical |
| Upgrade failure injected between file replacements | Original release automatically restored |
| Explicit rollback after successful fixture upgrade | Original complete inventory restored |
| Fixture evidence, authorization, ERROR result, plan and token | Bytes and modes retained |
| Pinned manifest and exact archive inventory | PASS, eight runtime files plus manifest |
| Extracted archive manifest verification | All eight files PASS |
| Runtime inventory delta against installed V1 | Only `worker.py` changes |
| Installed V1 worker after staging work | Original hash retained |

The ownership regression uses Git's `GIT_TEST_ASSUME_DIFFERENT_OWNER=1` in
disposable fixtures. It trusts the temporary parent on its command line so
the source alone exercises the ownership refusal. The correction supplies
the source exception through the temporary config. This is a staging
simulation; the actual UID 981 diagnostic was supplied by the operator.
Git pushes in the suite target disposable local bare repositories. No test
contacts GitHub or uses a real token or owner authorization.

## Release and next operator action

`dist/alfred-draft-pr-publisher-v1.1.0.tar.gz` SHA-256:

`bacefa3958db55d6bb5b4591e71902aeae55ba8002ffdebb72015dfa309b1052`

Pinned `draft_pr_publisher/release.sha256` SHA-256:

`926c925fedcaad40ef9240c2558ff9d10f241329f290a99e212a449f1c66442e`

New worker SHA-256:

`051ed86f1fe07260fd663636b665bbef5ddab6c2b8852ecc0a777264ee944ec3`

The reviewed commands are in `draft_pr_publisher/UPGRADE_V1_1_0.md`. They
replace only the installed worker and manifest, preserve the original pair
in a protected rollback directory, and require no service restart.

The baseline remains `9000574c4c8807e84c4350e2fd342deeba341d7d`, final revision
`89ba188f8a2f801d433a30c9c21363efb3e1043d`, branch
`alfred/dev-v1-accept/T-0002-89ba188f8a2f`, destination
`hrsnyde1/alfred-dev-v1-acceptance`, and base `main`.
The existing publication plan digest
`511fa533fd9dc5bb41d51bff1baa21b28a54b8b0b670e5b3f0f602a78d38b903`
and all evidence/authorization validation contracts are unchanged by the fix.

No staging code blocker remains. Host installation and any later publication
attempt are separate operator actions. This work did not restart services,
change credentials or source permissions, issue authorization, modify protected
evidence, regenerate a plan, overwrite the original ERROR result, or publish.
