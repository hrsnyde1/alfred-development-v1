"""Deterministic handoff.7 review archive. Staging only; never installs.

Same immutable, reproducible format as development_challenge/build_handoff_release.py.
"""

import argparse
import hashlib
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "development_challenge"))
from build_handoff_release import archive, manifest, tree

NAME = "alfred-fresh-v1-1.0.1-development-handoff.7"
PAYLOAD = (
    "development_handoff7/HOST.md",
    "development_handoff7/install_patch.py",
    "development_handoff7/installed-after.sha256",
    "development_handoff7/installed-sha256.json",
    "development_handoff7/staging-tests.xml",
    "fresh_v1/host.py",
    "tests/test_development_handoff7_upgrade.py",
    "tests/test_root_clone_ownership.py",
    "verification/role_sandbox_preflight.py",
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
            files["development_handoff7/install_patch.py"]
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
