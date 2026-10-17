"""Staging-only transaction CLI. All roots must carry the temporary-root marker."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .release import StagingTransaction


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("verify", "install", "recover", "rollback"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--transaction", type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    installer = StagingTransaction(args.root, args.payload, manifest)
    if args.action == "verify":
        installer.verify()
        result = {"status": "verified", "scope": "isolated-staging-only"}
    elif args.action == "install":
        transaction = installer.install()
        result = {"status": "committed", "scope": "isolated-staging-only", "transaction": str(transaction)}
    else:
        if args.transaction is None:
            parser.error("--transaction required for recover/rollback")
        if args.action == "recover":
            installer.recover(args.transaction)
        else:
            installer.rollback(args.transaction)
        result = {"status": "rolled_back", "scope": "isolated-staging-only"}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
