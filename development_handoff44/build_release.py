"""Deterministic handoff.44 review archive. Staging only; never installs.

Same immutable, reproducible format as development_challenge/build_handoff_release.py.
Also writes development_handoff44/release.json, the pins `alfred-dev-ops install 44` reads.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB / "development_challenge"))
from build_handoff_release import archive, manifest, tree

NAME = "alfred-fresh-v1-1.0.1-development-handoff.44"
PAYLOAD = (
    "development_handoff44/HOST.md",
    "development_handoff44/alfred-dev-board.service",
    "development_handoff44/alfred-dev-board.timer",
    "development_handoff44/alfred-photon-clear",
    "development_handoff44/alfred-photon-requests.path",
    "development_handoff44/alfred-photon-watchdog.service",
    "development_handoff44/alfred-photon.sysusers.conf",
    "development_handoff44/alfred-photon.tmpfiles.conf",
    "development_handoff44/install_patch.py",
    "development_handoff44/installed-after.sha256",
    "development_handoff44/installed-sha256.json",
    "development_handoff44/staging-tests.xml",
    "fresh_v1/dev_board.py",
    "fresh_v1/photon_watchdog.py",
    "tests/test_dev_board.py",
    "tests/test_development_handoff44_upgrade.py",
    "tests/test_photon_stalls.py",
)
INSTALLER = "development_handoff44/install_patch.py"


def build():
    dist = LAB / "dist"
    release, target = dist / NAME, dist / (NAME + ".tar.gz")
    checksum = target.with_name(target.name + ".sha256")
    pins_path = LAB / "development_handoff44" / "release.json"
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
        "installed_after": "development_handoff44/installed-after.sha256",
        "preflight": None,
        "restart": [],
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
