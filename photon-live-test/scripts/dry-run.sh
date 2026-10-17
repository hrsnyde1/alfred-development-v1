#!/usr/bin/env bash
set -euo pipefail
runtime_root=$(cd -- "$(dirname -- "$0")/.." && pwd -P)
"$runtime_root/bin/node" "$runtime_root/scripts/integrity.mjs" --verify
"$runtime_root/bin/node" --check "$runtime_root/vendor/node_modules/@spectrum-ts/imessage/dist/index.js"
"$runtime_root/bin/node" "$runtime_root/src/runtime.mjs" --dry-run
"$runtime_root/bin/node" --test --test-isolation=none --test-reporter=tap "$runtime_root"/tests/*.test.mjs
