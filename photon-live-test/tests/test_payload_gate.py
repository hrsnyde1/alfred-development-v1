import copy
import gzip
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("payload_gate", ROOT / "same-server/payload_gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class PayloadGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".payload-gate-", dir=ROOT / "tests")
        self.base = Path(self.temporary.name)
        self.source = self.base / "source"
        (self.source / "bin").mkdir(parents=True)
        (self.source / "src").mkdir()
        (self.source / "bin/node").write_bytes(b"pinned node fixture\n")
        (self.source / "src/test.txt").write_bytes(b"payload fixture\n")
        (self.source / "src/link").symlink_to("test.txt")
        self.write_manifest()

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self):
        records = []
        for file in sorted(self.source.rglob("*")):
            if file.is_dir() or file.name == "MANIFEST.sha256" or "dist" in file.relative_to(self.source).parts:
                continue
            relative = file.relative_to(self.source).as_posix()
            if file.is_symlink():
                digest = hashlib.sha256(os.fsencode(os.readlink(file))).hexdigest()
                kind = "L"
            else:
                digest = gate.sha256_file(file)
                kind = "F"
            records.append(f"{kind} {digest} {relative}")
        (self.source / "MANIFEST.sha256").write_text("\n".join(sorted(records)) + "\n")

    def build(self):
        output = self.source / "dist/payload.tar.gz"
        return output, *gate.build_payload(self.source, output)

    def mutate_archive(self, original, name, change):
        output = self.base / name
        with tarfile.open(original, "r:gz") as source:
            with output.open("wb") as raw:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                    with tarfile.open(fileobj=zipped, mode="w|", format=tarfile.PAX_FORMAT) as result:
                        for member in source.getmembers():
                            amended = copy.copy(member)
                            change(amended)
                            content = source.extractfile(member).read() if member.isfile() else None
                            result.addfile(amended, io.BytesIO(content) if content is not None else None)
        return output, gate.sha256_file(output)

    def test_pinned_snapshot_verifies_and_extracts_without_running_payload(self):
        archive, digest, manifest_digest = self.build()
        self.assertEqual(gate.verify_archive(archive, digest, manifest_digest), 3)
        destination = self.base / "installed"
        self.assertEqual(gate.verify_archive(archive, digest, manifest_digest, True, destination), 3)
        self.assertEqual((destination / "src/test.txt").read_bytes(), b"payload fixture\n")
        self.assertEqual((destination / "bin/node").stat().st_mode & 0o777, 0o555)
        self.assertEqual((destination / "src/test.txt").stat().st_mode & 0o777, 0o444)
        self.assertEqual((destination / "src/link").resolve(), destination / "src/test.txt")

    def test_modified_payload_and_forged_manifest_fail_against_approval(self):
        archive, digest, manifest_digest = self.build()
        modified = self.base / "modified.tar.gz"
        modified.write_bytes(archive.read_bytes() + b"tamper")
        with self.assertRaisesRegex(gate.PayloadError, "PAYLOAD_DIGEST_MISMATCH"):
            gate.verify_archive(modified, digest, manifest_digest)
        self.source.joinpath("src/test.txt").write_bytes(b"forged content\n")
        self.write_manifest()
        forged, forged_digest, _ = self.build_again("forged.tar.gz")
        with self.assertRaisesRegex(gate.PayloadError, "MANIFEST_DIGEST_MISMATCH"):
            gate.verify_archive(forged, forged_digest, manifest_digest)
        with self.assertRaisesRegex(gate.PayloadError, "EMBEDDED_GATE_MISMATCH"):
            gate.verify_archive(archive, digest, manifest_digest,
                                approved_gate_digest="0" * 64)

    def build_again(self, name):
        output = self.source / "dist" / name
        return output, *gate.build_payload(self.source, output)

    def test_symlink_swap_and_escape_fail(self):
        archive, digest, manifest_digest = self.build()
        link = self.base / "swapped.tar.gz"
        link.symlink_to(archive)
        with self.assertRaisesRegex(gate.PayloadError, "ARCHIVE_FILE_INVALID"):
            gate.verify_archive(link, digest, manifest_digest)
        hostile, hostile_digest = self.mutate_archive(
            archive, "escape.tar.gz", lambda member: setattr(member, "linkname", "/etc/passwd")
            if member.name == "src/link" else None)
        with self.assertRaisesRegex(gate.PayloadError, "SYMLINK_ESCAPE"):
            gate.verify_archive(hostile, hostile_digest, manifest_digest)

    def test_hardlink_special_owner_acl_and_executable_changes_fail(self):
        archive, _, manifest_digest = self.build()
        for label, mutator, error in [
            ("hardlink", lambda m: setattr(m, "type", tarfile.LNKTYPE) if m.name == "src/test.txt" else None,
             "HARDLINK_OR_SPECIAL_FILE"),
            ("fifo", lambda m: setattr(m, "type", tarfile.FIFOTYPE) if m.name == "src/test.txt" else None,
             "HARDLINK_OR_SPECIAL_FILE"),
            ("owner", lambda m: setattr(m, "uid", 1000) if m.name == "src/test.txt" else None,
             "DUPLICATE_OR_UNEXPECTED_OWNER"),
            ("executable", lambda m: setattr(m, "mode", 0o555) if m.name == "src/test.txt" else None,
             "EXECUTABLE_MODE_CHANGED"),
            ("acl", lambda m: m.pax_headers.update({"SCHILY.xattr.system.posix_acl_access": "forged"})
             if m.name == "src/test.txt" else None, "UNEXPECTED_PAX_METADATA"),
        ]:
            with self.subTest(label=label):
                hostile, hostile_digest = self.mutate_archive(archive, label + ".tar.gz", mutator)
                with self.assertRaisesRegex(gate.PayloadError, error):
                    gate.verify_archive(hostile, hostile_digest, manifest_digest)

    def test_path_traversal_fails(self):
        archive, _, manifest_digest = self.build()
        hostile, hostile_digest = self.mutate_archive(
            archive, "traversal.tar.gz", lambda member: setattr(member, "name", "../outside")
            if member.name == "src/test.txt" else None)
        with self.assertRaisesRegex(gate.PayloadError, "PATH_TRAVERSAL"):
            gate.verify_archive(hostile, hostile_digest, manifest_digest)

    def test_source_hardlink_special_and_unapproved_changes_fail(self):
        other = self.base / "other"
        os.link(self.source / "src/test.txt", other)
        with self.assertRaisesRegex(gate.PayloadError, "SOURCE_HARDLINK_OR_SIZE"):
            self.build()
        other.unlink()
        os.mkfifo(self.source / "src/fifo")
        with self.assertRaisesRegex(gate.PayloadError, "SOURCE_SPECIAL_FILE"):
            self.build()
        (self.source / "src/fifo").unlink()
        (self.source / "src/test.txt").write_bytes(b"changed without manifest\n")
        with self.assertRaisesRegex(gate.PayloadError, "SOURCE_MANIFEST_MISMATCH"):
            self.build()

    def test_interrupted_and_partial_install_fail_closed(self):
        archive, digest, manifest_digest = self.build()
        destination = self.base / "partial"
        with self.assertRaisesRegex(gate.PayloadError, "INJECTED_INTERRUPTION"):
            gate.verify_archive(archive, digest, manifest_digest, True, destination, interrupt_after=1)
        self.assertTrue(destination.exists())
        with self.assertRaisesRegex(gate.PayloadError, "DESTINATION_ALREADY_EXISTS"):
            gate.verify_archive(archive, digest, manifest_digest, True, destination)
        destination = self.base / "preexisting"
        destination.mkdir()
        with self.assertRaisesRegex(gate.PayloadError, "DESTINATION_ALREADY_EXISTS"):
            gate.verify_archive(archive, digest, manifest_digest, True, destination)

    def test_member_count_and_entry_size_caps_fail_before_extraction(self):
        archive, digest, manifest_digest = self.build()
        with patch.object(gate, "MAX_MEMBERS", 2):
            with self.assertRaisesRegex(gate.PayloadError, "TOO_MANY_MEMBERS"):
                gate.verify_archive(archive, digest, manifest_digest)
        with patch.object(gate, "MAX_ENTRY", 10):
            with self.assertRaisesRegex(gate.PayloadError, "PAYLOAD_SIZE_INVALID"):
                gate.verify_archive(archive, digest, manifest_digest)

    def test_mutable_staging_source_cannot_change_pinned_snapshot(self):
        archive, digest, manifest_digest = self.build()
        private = self.base / "root-private-copy.tar.gz"
        private.write_bytes(archive.read_bytes())
        self.source.joinpath("src/test.txt").write_bytes(b"changed after snapshot\n")
        self.assertEqual(gate.verify_archive(private, digest, manifest_digest), 3)

    def test_bounded_handoff_rejects_forgery_fifo_symlink_hardlink_and_size(self):
        source = self.base / "source.tar.gz"
        target = self.base / "quarantine.tar.gz"
        source.write_bytes(b"approved payload")
        approved = gate.sha256_file(source)
        gate.bounded_handoff(source, target, approved, limit=100)
        self.assertEqual(target.read_bytes(), source.read_bytes())
        target.unlink()
        with self.assertRaisesRegex(gate.PayloadError, "PAYLOAD_DIGEST_MISMATCH"):
            gate.bounded_handoff(source, target, "0" * 64, limit=100)
        self.assertFalse(target.exists())
        source.unlink()
        os.mkfifo(source)
        with self.assertRaisesRegex(gate.PayloadError, "SOURCE_TYPE_OR_SIZE_INVALID"):
            gate.bounded_handoff(source, target, approved, limit=100)
        source.unlink()
        source.symlink_to(self.source / "bin/node")
        with self.assertRaises(OSError):
            gate.bounded_handoff(source, target, approved, limit=100)
        source.unlink()
        source.write_bytes(b"approved payload")
        other = self.base / "hardlink"
        os.link(source, other)
        with self.assertRaisesRegex(gate.PayloadError, "SOURCE_TYPE_OR_SIZE_INVALID"):
            gate.bounded_handoff(source, target, approved, limit=100)
        other.unlink()
        with self.assertRaisesRegex(gate.PayloadError, "SOURCE_TYPE_OR_SIZE_INVALID"):
            gate.bounded_handoff(source, target, approved, limit=4)
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(gate.PayloadError, "SOURCE_OWNER_OR_MODE_INVALID"):
            gate.bounded_handoff(source, target, approved, limit=100,
                                 expected_uid=os.getuid() + 1)
        with self.assertRaisesRegex(gate.PayloadError, "SOURCE_OWNER_OR_MODE_INVALID"):
            gate.bounded_handoff(source, target, approved, limit=100,
                                 expected_mode=0o444)

    def test_handoff_uses_open_descriptor_and_rejects_mutation_or_interruption(self):
        source = self.base / "approved.tar.gz"
        target = self.base / "quarantine.tar.gz"
        source.write_bytes(b"original approved bytes")
        approved = gate.sha256_file(source)

        def swap_path():
            source.rename(self.base / "original.tar.gz")
            source.write_bytes(b"substituted bytes")

        gate.bounded_handoff(source, target, approved, after_open=swap_path)
        self.assertEqual(target.read_bytes(), b"original approved bytes")
        target.unlink()
        source.unlink()
        source.write_bytes(b"original approved bytes")

        def mutate_open_file():
            source.write_bytes(b"mutated content")

        with self.assertRaisesRegex(gate.PayloadError, "SOURCE_CHANGED_DURING_COPY"):
            gate.bounded_handoff(source, target, approved, on_block=mutate_open_file)
        self.assertFalse(target.exists())
        source.write_bytes(b"original approved bytes")
        with self.assertRaisesRegex(gate.PayloadError, "INJECTED_INTERRUPTION"):
            gate.bounded_handoff(source, target, approved, interrupt_after=1)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
