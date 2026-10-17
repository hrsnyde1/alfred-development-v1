"""Deterministic development-handoff review archive. Staging only; never installs.

Builds dist/<NAME>/ (payload + MANIFEST.sha256), dist/<NAME>.tar.gz and its
.sha256 file. Existing release outputs are immutable and are never overwritten.
`--reproduce DIR` rebuilds an existing release tree in memory and prints its
archive digest, to show the builder matches a previously pinned archive.
"""

import argparse
import gzip
import hashlib
import io
import tarfile
from pathlib import Path

LAB = Path(__file__).resolve().parents[1]
NAME = "alfred-fresh-v1-1.0.1-development-handoff.2"
PAYLOAD = (
    "developer_v1/owner_grants.py",
    "developer_v1/release.sha256",
    "developer_v1/stage_approval.py",
    "developer_v1/trusted_intake_development.py",
    "development_challenge/OWNER_CONTRACT_CORRECTION.md",
    "development_challenge/REPORT.md",
    "development_challenge/TESTS.md",
    "development_challenge/install_patch.py",
    "development_challenge/installed-after.sha256",
    "development_challenge/installed-sha256.json",
    "development_challenge/node-tests.tap",
    "development_challenge/runtime.patch",
    "development_challenge/sidecar/development-observe.mjs",
    "development_challenge/staging-tests.xml",
    "development_challenge/test-selection.txt",
    "development_challenge/tests/development-observe.test.mjs",
    "fresh_v1/host.py",
    "tests/test_approval_evidence_host_v1.py",
    "tests/test_developer_execution_v1.py",
    "tests/test_development_challenge_delivery.py",
    "tests/test_development_diagnostics_upgrade.py",
    "tests/test_development_handoff_upgrade.py",
    "tests/test_handoff_dependency_owner_contract.py",
)


def manifest(files):
    return "".join(
        hashlib.sha256(raw).hexdigest() + "  " + name + "\n"
        for name, raw in sorted(files.items())
    ).encode()


def archive(name, files):
    entries = {"MANIFEST.sha256": manifest(files), **dict(sorted(files.items()))}
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.USTAR_FORMAT) as tar:
            for relative, raw in entries.items():
                info = tarfile.TarInfo(name + "/" + relative)
                info.size, info.mode = len(raw), 0o644
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ""
                tar.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


def tree(directory):
    return {
        str(p.relative_to(directory)): p.read_bytes()
        for p in directory.rglob("*")
        if p.is_file() and p.name != "MANIFEST.sha256"
    }


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
        "payload_files": len(files),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reproduce", type=Path)
    args = parser.parse_args()
    if args.reproduce:
        raw = archive(args.reproduce.name, tree(args.reproduce))
        print(hashlib.sha256(raw).hexdigest())
    else:
        print(build())


if __name__ == "__main__":
    main()
