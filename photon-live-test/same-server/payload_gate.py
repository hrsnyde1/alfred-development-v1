#!/usr/bin/env python3
"""Pinned payload builder/verifier. Root execution requires an external hash approval first.

The root operator must copy this file to a private root-owned path and verify its
SHA-256 against a separately protected approval record *before* invoking Python.
No staging path is executed by the installer.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import pwd
from pathlib import Path, PurePosixPath
import re
import resource
import stat
import sys
import tarfile

MAX_ARCHIVE = 512 * 1024 * 1024
MAX_PAYLOAD = 700 * 1024 * 1024
MAX_MEMBERS = 20000
MAX_ENTRY = 256 * 1024 * 1024
MAX_GATE = 256 * 1024
MAX_MANIFEST = 4 * 1024 * 1024
HEX64 = re.compile(r"^[0-9a-f]{64}$")
APPROVAL_KEYS = {"payload_sha256", "manifest_sha256", "gate_sha256"}


class PayloadError(Exception):
    pass


def sha256_file(name):
    digest = hashlib.sha256()
    with open(name, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def no_acl(name):
    attrs = os.listxattr(name, follow_symlinks=False)
    if any(attr.startswith("system.posix_acl_") for attr in attrs):
        raise PayloadError("UNEXPECTED_ACL")


def canonical(name):
    if not isinstance(name, str) or not name or len(name.encode("utf-8")) > 4096 or \
            "\\" in name or "\x00" in name:
        raise PayloadError("INVALID_MEMBER_NAME")
    parts = name.split("/")
    if name.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise PayloadError("PATH_TRAVERSAL")
    return name


def parse_manifest(data):
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise PayloadError("MANIFEST_ENCODING") from error
    if not lines or data != ("\n".join(lines) + "\n").encode():
        raise PayloadError("MANIFEST_FORMAT")
    if lines != sorted(lines):
        raise PayloadError("MANIFEST_ORDER")
    expected = {}
    for line in lines:
        match = re.fullmatch(r"([FL]) ([0-9a-f]{64}) (.+)", line)
        if not match:
            raise PayloadError("MANIFEST_RECORD_INVALID")
        kind, digest, name = match.groups()
        canonical(name)
        if name == "MANIFEST.sha256" or name == "dist" or name.startswith("dist/") or name in expected:
            raise PayloadError("MANIFEST_PATH_INVALID")
        expected[name] = (kind, digest)
    return expected


def source_entries(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise PayloadError("SOURCE_ROOT_INVALID")
    expected = {}
    directories = set()
    entries = []
    source_uid = os.getuid()

    def visit(directory):
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            rel = Path(entry.path).relative_to(root).as_posix()
            if rel == "dist" or rel.startswith("dist/"):
                continue
            canonical(rel)
            info = os.lstat(entry.path)
            if info.st_uid != source_uid:
                raise PayloadError("UNEXPECTED_SOURCE_OWNER")
            no_acl(entry.path)
            if stat.S_ISDIR(info.st_mode):
                directories.add(rel)
                entries.append((rel, "D", entry.path, None))
                visit(entry.path)
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink != 1 or info.st_size > MAX_ENTRY:
                    raise PayloadError("SOURCE_HARDLINK_OR_SIZE")
                digest = sha256_file(entry.path)
                entries.append((rel, "F", entry.path, digest))
                if rel != "MANIFEST.sha256":
                    expected[rel] = ("F", digest)
            elif stat.S_ISLNK(info.st_mode):
                target = os.readlink(entry.path)
                if target.startswith("/") or "\x00" in target:
                    raise PayloadError("SOURCE_SYMLINK_ESCAPE")
                resolved = (Path(entry.path).parent / target).resolve(strict=True)
                if not resolved.is_relative_to(root.resolve()):
                    raise PayloadError("SOURCE_SYMLINK_ESCAPE")
                digest = hashlib.sha256(os.fsencode(target)).hexdigest()
                entries.append((rel, "L", entry.path, digest))
                expected[rel] = ("L", digest)
            else:
                raise PayloadError("SOURCE_SPECIAL_FILE")

    visit(root)
    manifest = (root / "MANIFEST.sha256").read_bytes()
    if parse_manifest(manifest) != expected:
        raise PayloadError("SOURCE_MANIFEST_MISMATCH")
    return entries, manifest


def build_payload(root, archive):
    entries, manifest = source_entries(root)
    archive = Path(archive)
    if archive.exists() or archive.is_symlink():
        raise PayloadError("ARCHIVE_ALREADY_EXISTS")
    if archive.parent.resolve() != (Path(root) / "dist").resolve():
        raise PayloadError("ARCHIVE_OUTSIDE_DIST")
    archive.parent.mkdir(mode=0o700, exist_ok=True)
    with open(archive, "xb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
                for name, kind, source, _ in entries:
                    info = tarfile.TarInfo(name)
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ""
                    if kind == "D":
                        info.type = tarfile.DIRTYPE
                        info.mode = 0o555
                    elif kind == "L":
                        info.type = tarfile.SYMTYPE
                        info.mode = 0o777
                        info.linkname = os.readlink(source)
                    else:
                        info.type = tarfile.REGTYPE
                        info.mode = 0o555 if name == "bin/node" else 0o444
                        info.size = os.lstat(source).st_size
                    if kind == "F":
                        with open(source, "rb") as stream:
                            tar.addfile(info, stream)
                    else:
                        tar.addfile(info)
        raw.flush()
        os.fsync(raw.fileno())
    # A source change during packing is detected by the full copied-archive check.
    verify_archive(archive, sha256_file(archive), hashlib.sha256(manifest).hexdigest(), extract=False)
    return sha256_file(archive), hashlib.sha256(manifest).hexdigest()


def _members(tar):
    members = []
    seen = {}
    directories = set()
    total = 0
    for member in tar:
        members.append(member)
        if len(members) > MAX_MEMBERS:
            raise PayloadError("TOO_MANY_MEMBERS")
        name = canonical(member.name)
        if name in seen or member.uid != 0 or member.gid != 0:
            raise PayloadError("DUPLICATE_OR_UNEXPECTED_OWNER")
        if set(member.pax_headers) - {"path", "linkpath"}:
            raise PayloadError("UNEXPECTED_PAX_METADATA")
        if member.type == tarfile.DIRTYPE:
            if member.mode != 0o555:
                raise PayloadError("DIRECTORY_MODE_INVALID")
            directories.add(name)
        elif member.type == tarfile.REGTYPE:
            if member.mode != (0o555 if name == "bin/node" else 0o444):
                raise PayloadError("EXECUTABLE_MODE_CHANGED")
            total += member.size
            if member.size > MAX_ENTRY or total > MAX_PAYLOAD:
                raise PayloadError("PAYLOAD_SIZE_INVALID")
        elif member.type == tarfile.SYMTYPE:
            if not member.linkname or len(member.linkname.encode("utf-8")) > 4096 or \
                    member.linkname.startswith("/") or "\x00" in member.linkname:
                raise PayloadError("SYMLINK_ESCAPE")
        else:
            raise PayloadError("HARDLINK_OR_SPECIAL_FILE")
        seen[name] = member
    return members, seen, directories


def bounded_handoff(source, destination, approved_digest, limit=MAX_ARCHIVE,
                    interrupt_after=None, after_open=None, on_block=None,
                    expected_uid=None, expected_gid=None, expected_mode=None):
    """Snapshot one untrusted regular file by descriptor into a private O_EXCL file.

    Digest approval, not the mutable source path, grants authority to the snapshot.
    Both source and destination are verified again by the root CLI before use.
    """
    if os.path.lexists(destination):
        raise PayloadError("DESTINATION_ALREADY_EXISTS")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    src = os.open(source, flags)
    dst = None
    try:
        if after_open is not None:
            after_open()
        before = os.fstat(src)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or \
                before.st_size <= 0 or before.st_size > limit:
            raise PayloadError("SOURCE_TYPE_OR_SIZE_INVALID")
        if (expected_uid is not None and before.st_uid != expected_uid) or \
                (expected_gid is not None and before.st_gid != expected_gid) or \
                (expected_mode is not None and stat.S_IMODE(before.st_mode) != expected_mode):
            raise PayloadError("SOURCE_OWNER_OR_MODE_INVALID")
        if any(attr.startswith("system.posix_acl_") for attr in os.listxattr(src)):
            raise PayloadError("UNEXPECTED_ACL")
        dst = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                      os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
        digest = hashlib.sha256()
        copied = 0
        while True:
            block = os.read(src, min(1024 * 1024, limit + 1 - copied))
            if not block:
                break
            copied += len(block)
            if copied > limit:
                raise PayloadError("SOURCE_SIZE_LIMIT")
            view = memoryview(block)
            while view:
                view = view[os.write(dst, view):]
            digest.update(block)
            if on_block is not None:
                on_block()
            if interrupt_after is not None and copied >= interrupt_after:
                raise PayloadError("INJECTED_INTERRUPTION")
        after = os.fstat(src)
        if (copied != before.st_size or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise PayloadError("SOURCE_CHANGED_DURING_COPY")
        if digest.hexdigest() != approved_digest:
            raise PayloadError("PAYLOAD_DIGEST_MISMATCH")
        os.fsync(dst)
        if os.fstat(dst).st_size != copied:
            raise PayloadError("SNAPSHOT_SIZE_MISMATCH")
        os.close(dst)
        dst = None
        parent = os.open(os.path.dirname(destination), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except BaseException:
        if dst is not None:
            os.close(dst)
        if os.path.lexists(destination):
            os.unlink(destination)
        raise
    finally:
        os.close(src)


def root_limits():
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_ARCHIVE, MAX_ARCHIVE))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def verify_archive(archive, approved_digest, approved_manifest_digest, extract=False, destination=None,
                   interrupt_after=None, approved_gate_digest=None):
    archive = Path(archive)
    info = os.lstat(archive)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_ARCHIVE:
        raise PayloadError("ARCHIVE_FILE_INVALID")
    no_acl(archive)
    if sha256_file(archive) != approved_digest:
        raise PayloadError("PAYLOAD_DIGEST_MISMATCH")
    with tarfile.open(archive, "r:gz") as tar:
        members, seen, directories = _members(tar)
        manifest_member = seen.get("MANIFEST.sha256")
        if manifest_member is None or manifest_member.type != tarfile.REGTYPE or \
                manifest_member.size > MAX_MANIFEST:
            raise PayloadError("MANIFEST_MISSING")
        manifest = tar.extractfile(manifest_member).read()
        if hashlib.sha256(manifest).hexdigest() != approved_manifest_digest:
            raise PayloadError("MANIFEST_DIGEST_MISMATCH")
        expected = parse_manifest(manifest)
        if approved_gate_digest is not None and expected.get("same-server/payload_gate.py") != \
                ("F", approved_gate_digest):
            raise PayloadError("EMBEDDED_GATE_MISMATCH")
        if set(seen) != set(expected) | {"MANIFEST.sha256"} | directories:
            raise PayloadError("PAYLOAD_INVENTORY_MISMATCH")
        implied_dirs = {str(PurePosixPath(name).parent) for name in seen if "/" in name}
        implied_dirs.discard(".")
        for name in list(implied_dirs):
            parent = PurePosixPath(name)
            while str(parent.parent) != ".":
                parent = parent.parent
                implied_dirs.add(str(parent))
        if directories != implied_dirs:
            raise PayloadError("DIRECTORY_INVENTORY_MISMATCH")
        for name, (kind, digest) in expected.items():
            member = seen[name]
            if kind == "F" and member.type != tarfile.REGTYPE or kind == "L" and member.type != tarfile.SYMTYPE:
                raise PayloadError("PAYLOAD_TYPE_MISMATCH")
            if kind == "L":
                if hashlib.sha256(os.fsencode(member.linkname)).hexdigest() != digest:
                    raise PayloadError("SYMLINK_HASH_MISMATCH")
                lexical = os.path.normpath(os.path.join(os.path.dirname(name), member.linkname))
                if lexical.startswith("../") or lexical in ("..", ".") or os.path.isabs(lexical):
                    raise PayloadError("SYMLINK_ESCAPE")
                if lexical not in seen:
                    raise PayloadError("SYMLINK_TARGET_MISSING")
        if not extract:
            # gzip-backed tar random seeks can re-decompress the whole archive.
            # Read in physical member order instead of manifest hash order.
            for member in members:
                if member.type == tarfile.REGTYPE and member.name != "MANIFEST.sha256" and \
                        hashlib.sha256(tar.extractfile(member).read()).hexdigest() != expected[member.name][1]:
                    raise PayloadError("FILE_HASH_MISMATCH")
            return len(expected)
        if destination is None or os.path.lexists(destination):
            raise PayloadError("DESTINATION_ALREADY_EXISTS")
        dest = Path(destination)
        os.mkdir(dest, 0o700)
        created = 0
        for name in sorted(directories, key=lambda item: (item.count("/"), item)):
            os.mkdir(dest / name, 0o700)
        for member in members:
            if member.type != tarfile.REGTYPE:
                continue
            target = dest / member.name
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            digest = hashlib.sha256()
            try:
                with tar.extractfile(member) as source:
                    while block := source.read(1024 * 1024):
                        remaining = memoryview(block)
                        while remaining:
                            written = os.write(fd, remaining)
                            remaining = remaining[written:]
                        digest.update(block)
                if member.name != "MANIFEST.sha256" and digest.hexdigest() != expected[member.name][1]:
                    raise PayloadError("FILE_HASH_MISMATCH")
                os.fchmod(fd, member.mode)
                os.fsync(fd)
            finally:
                os.close(fd)
            created += 1
            if interrupt_after is not None and created >= interrupt_after:
                raise PayloadError("INJECTED_INTERRUPTION")
        for member in members:
            if member.type == tarfile.SYMTYPE:
                os.symlink(member.linkname, dest / member.name)
        for member in members:
            if member.type == tarfile.SYMTYPE:
                resolved = Path(dest / member.name).resolve(strict=True)
                if not resolved.is_relative_to(dest.resolve()):
                    raise PayloadError("SYMLINK_ESCAPE")
        for name in sorted(directories, key=lambda item: (-item.count("/"), item)):
            os.chmod(dest / name, 0o555)
        os.chmod(dest, 0o555)
        for member in members:
            target = dest / member.name
            info = os.lstat(target)
            no_acl(target)
            if info.st_uid != os.getuid() or info.st_gid != os.getgid() or (
                member.type == tarfile.REGTYPE and (info.st_nlink != 1 or
                    stat.S_IMODE(info.st_mode) != member.mode)) or \
                    (member.type == tarfile.DIRTYPE and stat.S_IMODE(info.st_mode) != 0o555):
                raise PayloadError("EXTRACTED_OWNER_OR_LINK_INVALID")
        # Durable directory entries precede the acceptance marker.
        for directory in [*(dest / name for name in sorted(directories, key=lambda item: (-item.count("/"), item))), dest]:
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return len(expected)


def _read_approval(name):
    path = Path(name)
    if path != Path("/root/photon-reply-test/approved.json"):
        raise PayloadError("APPROVAL_PATH_INVALID")
    parent = os.lstat(path.parent)
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_gid != 0 or parent.st_mode & 0o077:
        raise PayloadError("APPROVAL_PARENT_UNPROTECTED")
    no_acl(path.parent)
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_gid != 0 or info.st_nlink != 1 or info.st_mode & 0o077:
        raise PayloadError("APPROVAL_FILE_UNPROTECTED")
    no_acl(path)
    data = json.loads(path.read_text())
    if set(data) != APPROVAL_KEYS or any(not isinstance(data[key], str) or not HEX64.fullmatch(data[key]) for key in APPROVAL_KEYS):
        raise PayloadError("APPROVAL_FORMAT_INVALID")
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "handoff", "verify"))
    parser.add_argument("--source")
    parser.add_argument("--archive")
    parser.add_argument("--destination")
    parser.add_argument("--approval")
    args = parser.parse_args()
    if args.action == "build":
        if os.geteuid() == 0 or not args.source or not args.archive:
            raise PayloadError("BUILD_REQUIRES_UNPRIVILEGED_SOURCE")
        digest, manifest_digest = build_payload(args.source, args.archive)
        print(f"PAYLOAD_SHA256={digest}\nMANIFEST_SHA256={manifest_digest}")
        return
    if os.geteuid() != 0 or not args.destination or not args.approval:
        raise PayloadError("ROOT_VERIFIER_ARGUMENTS_INVALID")
    approval = _read_approval(args.approval)
    self_info = os.lstat(__file__)
    if not stat.S_ISREG(self_info.st_mode) or self_info.st_uid != 0 or self_info.st_gid != 0 or \
            self_info.st_nlink != 1 or self_info.st_size > MAX_GATE or self_info.st_mode & 0o077:
        raise PayloadError("GATE_FILE_UNPROTECTED")
    no_acl(__file__)
    if sha256_file(__file__) != approval["gate_sha256"]:
        raise PayloadError("GATE_DIGEST_MISMATCH")
    root_limits()
    if args.action == "handoff":
        if args.archive or args.source != "/home/alfred/alfred-development-lab/milestone2/task-a/photon-live-test/dist/photon-reply-payload-v2.tar.gz" or \
                Path(args.destination) != Path("/srv/photon-reply-test/quarantine/payload.tar.gz"):
            raise PayloadError("HANDOFF_PATH_INVALID")
        parent = os.lstat(Path(args.destination).parent)
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != 0 or parent.st_gid != 0 or parent.st_mode & 0o077:
            raise PayloadError("ARCHIVE_PARENT_UNPROTECTED")
        no_acl(Path(args.destination).parent)
        staging_owner = pwd.getpwnam("alfred")
        bounded_handoff(args.source, args.destination, approval["payload_sha256"],
                        expected_uid=staging_owner.pw_uid, expected_gid=staging_owner.pw_gid,
                        expected_mode=0o444)
        print("PASS: approved payload snapshot")
        return
    if args.source or not args.archive or \
            Path(args.archive) != Path("/srv/photon-reply-test/quarantine/payload.tar.gz") or \
            Path(args.destination) != Path("/srv/photon-reply-test/quarantine/app"):
        raise PayloadError("INSTALL_PATH_INVALID")
    archive_parent = os.lstat(Path(args.archive).parent)
    if not stat.S_ISDIR(archive_parent.st_mode) or archive_parent.st_uid != 0 or \
            archive_parent.st_gid != 0 or archive_parent.st_mode & 0o077:
        raise PayloadError("ARCHIVE_PARENT_UNPROTECTED")
    no_acl(Path(args.archive).parent)
    info = os.lstat(args.archive)
    if info.st_uid != 0 or info.st_gid != 0 or info.st_mode & 0o077:
        raise PayloadError("ARCHIVE_NOT_ROOT_PROTECTED")
    count = verify_archive(args.archive, approval["payload_sha256"],
                           approval["manifest_sha256"], extract=True,
                           destination=args.destination,
                           approved_gate_digest=approval["gate_sha256"])
    marker = Path("/srv/photon-reply-test/quarantine/payload.ok")
    marker_fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    try:
        marker_content = (approval["payload_sha256"] + "\n").encode()
        if os.write(marker_fd, marker_content) != len(marker_content):
            raise PayloadError("MARKER_SHORT_WRITE")
        os.fsync(marker_fd)
    finally:
        os.close(marker_fd)
    fd = os.open(marker.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    print(f"PASS: verified root-controlled payload, {count} entries")


if __name__ == "__main__":
    try:
        main()
    except (PayloadError, OSError, tarfile.TarError, ValueError) as error:
        print(f"FAIL: payload gate ({error})", file=sys.stderr)
        sys.exit(1)
