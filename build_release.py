"""Build a deterministic, staging-only Task A review archive and SHA-256 file."""

from __future__ import annotations

import gzip
import hashlib
import io
from pathlib import Path
import stat
import tarfile


HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
NAME = "alfred-task-a-staging-0.1.3"
ROOT_FILES = {
    "APPROVAL_RECORD_CANDIDATE.json", "INDEPENDENT_SECURITY_REVIEW.md",
    "MIGRATION_RECOVERY.md", "PROTECTED_PATHS.md", "README.md",
    "TEST_RESULTS.md", "PHOTON_SECURITY_ARCHITECTURE.md",
    "ATTACHMENT_COMPATIBILITY.md", "adr-0003-conditional-photon-front.proposed.patch",
    "THREAT_MODEL.md", "INDEPENDENT_REVIEW_RESPONSE.md", "CHANGE_INVENTORY.md",
    "make_adr_patch.py", "make_photon_patch.py", "build_release.py",
}
PAYLOAD_DIRS = {"task_a", "tests", "templates", "patches"}
EXCLUDE = {".pytest_cache", "__pycache__"}


def files() -> list[Path]:
    result = []
    for path in HERE.rglob("*"):
        relative = path.relative_to(HERE)
        if relative.parts[0] not in ROOT_FILES | PAYLOAD_DIRS:
            continue
        if relative.parts[0] in ROOT_FILES and len(relative.parts) != 1:
            continue
        if any(part in EXCLUDE for part in relative.parts):
            continue
        if path.is_dir():
            continue
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError(f"non-regular payload: {path}")
        result.append(path)
    return sorted(result)


def main() -> None:
    DIST.mkdir(exist_ok=True)
    entries = files()
    sums = []
    for path in entries:
        relative = path.relative_to(HERE)
        sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative.as_posix()}")
    sums_blob = ("\n".join(sums) + "\n").encode()
    archive = DIST / f"{NAME}.tar.gz"
    checksum = DIST / (archive.name + ".sha256")
    if archive.exists() or checksum.exists():
        raise FileExistsError("immutable staging release already exists")
    with archive.open("xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode="w") as tar:
                for path in entries:
                    data = path.read_bytes()
                    entry = tarfile.TarInfo(f"{NAME}/{path.relative_to(HERE).as_posix()}")
                    entry.size = len(data)
                    entry.mode = 0o644
                    entry.uid = entry.gid = entry.mtime = 0
                    entry.uname = entry.gname = ""
                    tar.addfile(entry, io.BytesIO(data))
                entry = tarfile.TarInfo(f"{NAME}/SHA256SUMS")
                entry.size = len(sums_blob)
                entry.mode = 0o644
                entry.uid = entry.gid = entry.mtime = 0
                entry.uname = entry.gname = ""
                tar.addfile(entry, io.BytesIO(sums_blob))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    with checksum.open("x") as stream:
        stream.write(f"{digest}  {archive.name}\n")
    print(f"{archive.name}: {digest}")


if __name__ == "__main__":
    main()
