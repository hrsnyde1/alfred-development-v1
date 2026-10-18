"""Deterministic handoff.31 review archive. Staging only; never installs.

Same immutable, reproducible format as development_challenge/build_handoff_release.py.
Also writes development_handoff31/release.json, the pins `alfred-dev-ops install 31` reads.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "development_challenge"))
from build_handoff_release import archive, manifest, tree

NAME = "alfred-fresh-v1-1.0.1-development-handoff.31"
PAYLOAD = (
    "completion_integration/completion.py",
    "completion_integration/runtime.py",
    "developer_v1/owner_grants.py",
    "developer_v1/publication_approval.py",
    "developer_v1/trusted_intake_development.py",
    "developer_v1/undo_approval.py",
    "development_handoff31/HOST.md",
    "development_handoff31/delegation.json",
    "development_handoff31/install_patch.py",
    "development_handoff31/installed-after.sha256",
    "development_handoff31/installed-sha256.json",
    "development_handoff31/staging-tests.xml",
    "draft_pr_publisher/worker.py",
    "fresh_v1/diagnostics.py",
    "fresh_v1/handoffs.py",
    "fresh_v1/host.py",
    "fresh_v1/role.py",
    "fresh_v1/squads.py",
    "independent_qa/worker.py",
    "tests/test_auto_merge_undo.py",
    "tests/test_delegated_development_approval.py",
    "tests/test_development_handoff31_upgrade.py",
    # The preflight release.json names runs from inside the verified release.
    "verification/role_sandbox_preflight.py",
    "verification/role_sandbox_probe.py",
)
INSTALLER = "development_handoff31/install_patch.py"


def build():
    dist = LAB / "dist"
    release, target = dist / NAME, dist / (NAME + ".tar.gz")
    checksum = target.with_name(target.name + ".sha256")
    pins_path = LAB / "development_handoff31" / "release.json"
    if any(p.exists() for p in (release, target, checksum, pins_path)):
        raise FileExistsError("immutable release output already exists")
    files = {name: (LAB / name).read_bytes() for name in PAYLOAD}
    raw = archive(NAME, files)
    for name, data in {**files, "MANIFEST.sha256": manifest(files)}.items():
        path = release / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    target.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    checksum.write_text(digest + "  " + target.name + "\n")
    pins = {
        "schema": "alfred.development-release/1",
        "name": NAME,
        "archive_sha256": digest,
        "manifest_sha256": hashlib.sha256(manifest(files)).hexdigest(),
        "installer": INSTALLER,
        "installer_sha256": hashlib.sha256(files[INSTALLER]).hexdigest(),
        "installed_after": "development_handoff31/installed-after.sha256",
        "preflight": "verification/role_sandbox_preflight.py",
        "restart": ["alfred-development-intake.service"],
    }
    pins_path.write_text(json.dumps(pins, indent=2, sort_keys=True) + "\n")
    return {**pins, "payload_files": len(files)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reproduce", type=Path, help="an extracted release tree")
    args = parser.parse_args()
    if args.reproduce:
        print(hashlib.sha256(archive(args.reproduce.name, tree(args.reproduce))).hexdigest())
    else:
        print(json.dumps(build(), indent=2))


if __name__ == "__main__":
    main()
