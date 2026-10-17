"""Deterministic handoff.6 review archive. Staging only; never installs.

Same immutable, reproducible format as development_challenge/build_handoff_release.py.
"""

import argparse
import hashlib
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "development_challenge"))
from build_handoff_release import archive, manifest, tree

NAME = "alfred-fresh-v1-1.0.1-development-handoff.6"
PAYLOAD = (
    "developer_v1/real_worker.py",
    "developer_v1/release.sha256",
    "development_handoff6/HOST.md",
    "development_handoff6/install_patch.py",
    "development_handoff6/installed-after.sha256",
    "development_handoff6/installed-sha256.json",
    "development_handoff6/staging-tests.xml",
    "independent_reviewer/host-candidate-v5/independent_reviewer/release.sha256",
    "independent_reviewer/host-candidate-v5/independent_reviewer/worker.py",
    "tests/test_development_handoff6_upgrade.py",
    "tests/test_model_message_contract.py",
)


def build():
    dist = LAB / "dist"
    release, target = dist / NAME, dist / (NAME + ".tar.gz")
    checksum = target.with_name(target.name + ".sha256")
    if any(p.exists() for p in (release, target, checksum)):
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
    return {
        "archive_sha256": digest,
        "manifest_sha256": hashlib.sha256(manifest(files)).hexdigest(),
        "installer_sha256": hashlib.sha256(
            files["development_handoff6/install_patch.py"]
        ).hexdigest(),
        "payload_files": len(files),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reproduce", type=Path)
    args = parser.parse_args()
    if args.reproduce:
        print(hashlib.sha256(archive(args.reproduce.name, tree(args.reproduce))).hexdigest())
    else:
        print(build())


if __name__ == "__main__":
    main()
