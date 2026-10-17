# Native Photon provenance patch — staging verification

**Result (2026-10-14): PATCH CORRECTED — STAGING VERIFICATION PASS.** Source-level and synthetic evidence only; no Photon connection, production change or Gateway operation occurred.

## Correction and scope

The prior proposed patch omitted the comma after `nativeIsForward: z.boolean().optional()` in the Spectrum message schema. `git apply --check` tested patch applicability but did not validate JavaScript syntax. The earlier test exercised an extracted metadata mapper and used `node --check`; a complete ESM parse subsequently exposed `SyntaxError: Unexpected identifier 'formatting'` at the next schema property. The corrected patch adds that comma. No other adjacent syntax error was found in a complete parse and import of the patched module.

The corrected patch still copies `native.replyTargetGuid` and `native.threadOriginatorGuid` into **separate** optional metadata fields and carries `native.isForward`. It leaves Spectrum's existing combined reply content behavior unchanged. The patch targets the pinned installed `@spectrum-ts/imessage` 12.7.0 distribution only as a reviewable proposal; it has not been installed. A maintained upstream change must be made in source and rebuilt for any later deployment.

## Changed staging paths

| Path | Change |
|---|---|
| `patches/spectrum-native-reply-provenance.proposed.patch` | Add missing comma in proposed schema hunk. |
| `tests/native_reply_import_smoke.mjs` | New complete ESM parse, missing-comma rejection, actual pinned-dependency import and runtime schema checks. |
| `tests/native_reply_provenance.mjs` | Run direct, thread-fallback, missing, wrong-target and two-preview synthetic mapper fixtures. |
| `tests/test_native_reply_target_feasibility.py` | Add separate import regression; apply patch only in disposable Task A directory; link pinned dependencies read-only; verify installed hashes before/after. |
| `NATIVE_PHOTON_REPLY_TARGET_FEASIBILITY.md` | Correct test command, result count and syntax evidence. |
| `NATIVE_REPLY_PATCH_VERIFICATION.md` | This evidence record. |

No installed Hermes/Spectrum/Photon file changed. The disposable package and pytest scratch directories were created only inside Task A and were removed after testing.

## Exact checks and outcomes

Working directory for the checks below: `/home/alfred/alfred-development-lab/milestone2/task-a`, except the applicability check, whose working directory was `/home/alfred/.hermes/hermes-agent`.

1. **Pinned-source patch applicability** — `git apply --check /home/alfred/alfred-development-lab/milestone2/task-a/patches/spectrum-native-reply-provenance.proposed.patch` returned exit 0. This was read-only; no `git apply` was run against installed source.
2. **Disposable patch and full parse/import** — the Python test copies exact installed `index.js`, `index.d.ts` and package metadata under a temporary Task A directory; `git apply --check` and `git apply` both returned 0 there. It links the pinned dependency packages read-only. `tests/native_reply_import_smoke.mjs` runs with `/home/alfred/.hermes/tools/node-26.7.0-linux-x64/bin/node --experimental-vm-modules`, creates a `vm.SourceTextModule` from the **entire** patched JavaScript, verifies that removing the comma makes full parsing fail, dynamically imports the patched file, and checks the imported provider's `imessage.config().__definition.message.schema` with valid/invalid values for all three new fields. Both smoke assertions passed. It does not call `Spectrum(...)` or establish a network connection.
3. **Synthetic mapper fixtures** — `tests/native_reply_provenance.mjs` executed mapper bodies extracted from the pinned original and disposable patched copies. Direct target, thread-origin fallback, both fields missing, unrelated target, and two distinct overlapping preview targets produced the expected separate native metadata and existing combined fallback value. Both fixture assertions passed. The Python policy tests additionally denied unthreaded fallback-only, wrong, replayed, forged, expired and mismatched cases.
4. **Focused pytest suite** — final run: **20 passed, 0 failed, 0 skipped in 1.01 s**. The 19 earlier tests remain and one explicit full-module parse/import regression was added. Intermediate runs failed because the smoke test initially looked for the schema on `imessage.message`; the public provider wrapper exposes it at `imessage.config().__definition.message`. The corrected smoke test and final suite passed.
5. **Installed-original integrity** — SHA-256 of installed `@spectrum-ts/imessage` JavaScript and declaration files was checked before and after each disposable test. Both remained identical to their pre-correction hashes. A read-only search found no new `nativeReplyTargetGuid` fields in installed originals.

Exact final pytest command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 TMPDIR=/home/alfred/alfred-development-lab/milestone2/task-a PYTHONPATH=/home/alfred/.cache/uv/archive-v0/DK4n9G7xyVKZZ3KJ:/home/alfred/.cache/uv/archive-v0/Vd_UqZgwiCKPnjqT:/home/alfred/.cache/uv/archive-v0/yS-fDywY2zPwXlrb:/home/alfred/.cache/uv/archive-v0/zKTheZIblUKblIHq:/home/alfred/.cache/uv/archive-v0/0oYfnLum5o7lxH7f:/home/alfred/.cache/uv/archive-v0/I72leh8kvOwfxzxF:/home/alfred/.cache/uv/archive-v0/km5q1G6DQSLWVkaR:/home/alfred/.cache/uv/archive-v0/q2KGeVV7WpodnnBE:/home/alfred/.cache/uv/archive-v0/H6nw76zWZtAyqp8H:/home/alfred/.cache/uv/archive-v0/tnPDiOo2cFPD0KWg /home/alfred/alfred-development-lab/milestone2/.test-venv/bin/python -m pytest -q -rs -p no:cacheprovider --basetemp=/home/alfred/alfred-development-lab/milestone2/task-a/.pytest-native-reply tests/test_native_reply_target_feasibility.py
```

## SHA-256 evidence

| Artifact | SHA-256 |
|---|---|
| Installed `@spectrum-ts/imessage/dist/index.js` 12.7.0, unchanged | `2f7e13c432ad4e84f96b76eb3d59062d70d3d7e46737a7e15198a47ecda6ef24` |
| Installed `@spectrum-ts/imessage/dist/index.d.ts`, unchanged | `6a2278d14fd42a5603675b046fd1c8ad5c584da760e60b621f74059bf7dc3aa0` |
| Installed `@spectrum-ts/imessage/package.json`, unchanged | `9bedec8c79efebe5786a1daa341ec730501e7c9809703a7122ffd671a08455a6` |
| Installed `@spectrum-ts/core/dist/index.js` 12.7.0 | `2ca2e743caadb223a77159cc39749e38d672a54c8bc249ea0fdd665b2560b8ab` |
| Installed `@photon-ai/advanced-imessage/dist/chunk-KA2VVWQX.js` 2.1.0 | `f1c58ea76f38b61083814013c9b143d48f8c360fcea244f7f961fa73916a3853` |
| Installed sidecar `package-lock.json` | `2368d0b886d149c69dfb1fb2201ed7868bd751de2a88467b7848f2649241a313` |
| Corrected staging patch | `62d280e45e66b6880bf4e37d46aafbbf7cd4340368c5f85e6821f62c3cc62552` |
| Patched disposable `index.js` output | `9faf0be1530dde1e2f80b580d12377a1fa6b0995c3595794648237a2c8f241ee` |
| Patched disposable `index.d.ts` output | `06b9442709fa2832f3e1abb985291d87787dcf2c406b372cba1c59c75929f26d` |

The disposable patched outputs were removed after checksum collection. These hashes identify the exact module used for syntax/import testing; they do not certify live provider semantics.

## Remaining limit

The runtime import proves the patched package can load and expose distinct schema fields with the pinned dependencies. Synthetic fixtures do **not** establish whether a live Photon direct reply always sets `replyTargetGuid` to the outbound preview's actual ID across devices, delay or reconnect. That requires a separately authorized disposable-account test. No live connection was attempted.
