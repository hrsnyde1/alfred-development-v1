"""Resume only Phase A: verify existing files, then publish one checksum baseline.

No archive copy/extraction, package installation, service action or task operation.
The CLI requires root; ROOT is fixed and only replaced by isolated unit fixtures.
"""

import argparse
import ctypes
import hashlib
import io
import json
import os
import pwd
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path("/")
NAME = "alfred-fresh-v1-1.0.1-development-handoff.2"
REVIEW = "/root/alfred-fresh-v1-development-handoff-2-review"
BACKUP = "/root/alfred-fresh-v1-development-handoff-2-backup"
PAYLOAD_FILES = 23
ARCHIVE_SHA = "0f44351cca7ff57d15efc0d535c1a479a8db7ad36ea69506eafb34e7bb264c6f"
MANIFEST_SHA = "4083213e209cbdbeec41de9837f962d0a9c9d3ac3bc53deec9cd0dc7f1a48bfd"
SCRIPT_SHA = "8ae5244a94cf2e51a5c19492c8ea80bd6ad8178cefc1763c621677164a1cc95c"
INSTALLER_SHA = "f88b3f8ce01534ff256ff3773ee01be6e6df005b97156a62203215492981133d"
CONTEXT_SHA = "bda345a14ec110cf5b3118d7289204c304ba13795f9c9677351aa940d0ab198e"
PLAN_SHA = "e5b58519eb9943c7b9d093b19880c4a0c881dc5a2491c6e1c68b70ff10f032d6"
SPEC_SHA = "2474942d42eef568c150fda9da76601fe4b3bcd946546a22ca9ec6eeeaf22f58"
TASK = "/var/lib/alfred-v1-handoffs/dev-v1-accept/T-0003"
GRANTS = "/var/lib/alfred-development-grants"
PLAN = "/home/alfred/Alfred/gateway/cto-plans/dev-v1-accept-T-0003.json"
# The one unchanged dependency whose established owner is not root. Its digest,
# type, single link and no group/other write checks are unchanged.
DEPENDENCY_OWNERS = {
    "/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/index.mjs": "alfred"
}
UNITS = (
    "alfred-development-gateway.service",
    "alfred-development-evidence.service",
    "alfred-dev-executor.service",
    "alfred-dev-qa-runner.service",
    "alfred-dev-qa-snapshot.service",
    "alfred-dev-qa-auth.service",
)


class Blocked(ValueError):
    pass


def require(ok, checkpoint):
    if not ok:
        raise Blocked(checkpoint)


def host(name):
    return ROOT / name.lstrip("/")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, *, uid=None, private=False):
    for parent in (path, *path.parents):
        require(not parent.is_symlink(), "symlink: " + str(parent))
        if parent == ROOT:
            break
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise Blocked(
            f"read_failed: {path}: {type(exc).__name__}: errno={exc.errno}"
        ) from None
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            "regular_single_link: " + str(path),
        )
        require(uid is None or before.st_uid == uid, "ownership: " + str(path))
        require(
            not before.st_mode & (0o077 if private else 0o022),
            "protection: " + str(path),
        )
        raw = stream.read()
        after = os.fstat(stream.fileno())
        require(
            (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            "changed_while_reading: " + str(path),
        )
    return raw


def pinned(path, sha, *, private=False, uid=None):
    raw = read(path, uid=os.geteuid() if uid is None else uid, private=private)
    require(digest(raw) == sha, "sha256_mismatch: " + str(path))
    return raw


def verify_package():
    pinned(host("/root/alfred-fresh-v1-phase-a-prepare.sh"), SCRIPT_SHA, private=True)
    parent = host(REVIEW)
    info = parent.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and not parent.is_symlink()
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "protected_review_directory",
    )
    archive = pinned(host("/root/" + NAME + ".tar.gz"), ARCHIVE_SHA, private=True)
    release = parent / NAME
    info = release.lstat()
    require(
        stat.S_ISDIR(info.st_mode)
        and not release.is_symlink()
        and info.st_uid == os.geteuid()
        and not info.st_mode & 0o022,
        "protected_release_directory",
    )
    manifest = pinned(release / "MANIFEST.sha256", MANIFEST_SHA)
    inventory = {}
    for line in manifest.decode().splitlines():
        sha, name = line.split("  ", 1)
        require(
            re.fullmatch(r"[0-9a-f]{64}", sha)
            and name not in inventory
            and not Path(name).is_absolute()
            and ".." not in Path(name).parts,
            "release_manifest_path_or_digest",
        )
        inventory[name] = sha
        pinned(release / name, sha)
    require(len(inventory) == PAYLOAD_FILES, "release_inventory_count")
    actual = set()
    for p in release.rglob("*"):
        require(not p.is_symlink(), "release_symlink")
        s = p.lstat()
        require(
            s.st_uid == os.geteuid() and not s.st_mode & 0o022,
            "release_ownership_or_mode: " + str(p),
        )
        require(
            stat.S_ISREG(s.st_mode) or stat.S_ISDIR(s.st_mode), "release_special_file"
        )
        if p.is_file():
            actual.add(str(p.relative_to(release)))
    require(actual == set(inventory) | {"MANIFEST.sha256"}, "release_inventory_differs")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        members = tar.getmembers()
        require(
            len(members) == PAYLOAD_FILES + 1
            and len({m.name for m in members}) == PAYLOAD_FILES + 1,
            "archive_inventory_count",
        )
        for member in members:
            require(
                member.isfile()
                and member.name.startswith(NAME + "/")
                and ".." not in Path(member.name).parts,
                "archive_member_type_or_path",
            )
            name = member.name.removeprefix(NAME + "/")
            require(
                name in actual
                and tar.extractfile(member).read()
                == read(release / name, uid=os.geteuid()),
                "archive_extracted_bytes_differ: " + name,
            )
    pinned(release / "development_challenge/install_patch.py", INSTALLER_SHA)
    require(
        not os.path.lexists(host(BACKUP)),
        "installation_backup_already_exists",
    )
    return release


def idle():
    result = subprocess.run(
        [
            "systemctl",
            "show",
            *UNITS,
            "-p",
            "Id",
            "-p",
            "ActiveState",
            "-p",
            "SubState",
            "-p",
            "MainPID",
            "-p",
            "ControlPID",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    records = [
        dict(line.split("=", 1) for line in block.splitlines() if "=" in line)
        for block in result.stdout.strip().split("\n\n")
    ]
    require({r.get("Id") for r in records} == set(UNITS), "worker_inventory")
    for r in records:
        require(
            (
                r.get("ActiveState"),
                r.get("SubState"),
                r.get("MainPID"),
                r.get("ControlPID"),
            )
            == ("inactive", "dead", "0", "0"),
            "worker_not_idle: " + r["Id"],
        )


def task_and_approvals():
    base = host(TASK)
    for name, size, mtime in (
        ("plan.attempt.json", 60, 1792181749323796085),
        ("development-challenge.attempt.json", 77, 1792187986367039147),
    ):
        raw = read(base / name, uid=os.geteuid(), private=True)
        s = (base / name).stat()
        stage = "plan" if name == "plan.attempt.json" else "development-challenge"
        require(
            json.loads(raw) == {"stage": stage, "status": "uncertain_until_result"}
            and (s.st_size, s.st_mtime_ns) == (size, mtime),
            "original_attempt_changed: " + name,
        )
    require(
        not os.path.lexists(base / "development-challenge.result.json"),
        "challenge_result_already_exists",
    )
    context = read(base / "context.json", uid=os.geteuid())
    require(digest(context) == CONTEXT_SHA, "context_sha256")
    ctx = json.loads(context)
    require(
        ctx["baseline_revision"] == "596d91daf3311ad3aa0ee42e7220f699f58daf59"
        and ctx["scope"] == ["calculator.py", "test_calculator.py"],
        "frozen_baseline_or_scope",
    )
    require(
        digest(read(host(PLAN))) == ctx["plan_sha256"] == PLAN_SHA, "cto_plan_sha256"
    )
    require(digest(read(host(ctx["spec_path"]))) == SPEC_SHA, "canonical_spec_sha256")
    require(
        json.loads(read(base / "plan-recovery-1.result.json", uid=os.geteuid())) == ctx,
        "planning_result_context_binding",
    )
    grants = host(GRANTS)
    alfred_uid = pwd.getpwnam("alfred").pw_uid
    s = grants.lstat()
    require(
        stat.S_ISDIR(s.st_mode)
        and not grants.is_symlink()
        and s.st_uid == alfred_uid
        and stat.S_IMODE(s.st_mode) == 0o700,
        "grant_store_protection",
    )
    require(
        not list(grants.glob("pending-*.json"))
        and not list(grants.glob("publication-pending-*.json")),
        "pending_owner_approval",
    )

    def matches(value):
        if isinstance(value, dict):
            return (value.get("project"), value.get("task_id")) == (
                "dev-v1-accept",
                "T-0003",
            ) or any(matches(v) for v in value.values())
        return isinstance(value, list) and any(matches(v) for v in value)

    for p in grants.glob("*.json"):
        value = json.loads(read(p, uid=alfred_uid, private=True))
        if not p.name.startswith("request-route-"):
            require(not matches(value), "existing_T0003_approval_evidence: " + p.name)
    return ctx


def installed(release):
    pins = json.loads(
        read(release / "development_challenge/installed-sha256.json", uid=os.geteuid())
    )
    require(len(pins) == 14, "installed_contract_count")
    require(
        set(DEPENDENCY_OWNERS) <= set(pins), "dependency_owner_exception_outside_pins"
    )
    for name, sha in pins.items():
        owner = DEPENDENCY_OWNERS.get(name)
        uid = None if owner is None else pwd.getpwnam(owner).pw_uid
        require(uid != 0, "dependency_owner_exception_privileged: " + name)
        pinned(host(name), sha, uid=uid)
    seen = set()
    for line in (
        read(
            host("/opt/alfred-developer-v1/developer_v1/release.sha256"),
            uid=os.geteuid(),
        )
        .decode()
        .splitlines()
    ):
        sha, name = line.split("  ", 1)
        require(
            name.startswith("developer_v1/")
            and ".." not in Path(name).parts
            and name not in seen,
            "developer_inventory_path",
        )
        seen.add(name)
        pinned(host("/opt/alfred-developer-v1/" + name), sha)
    require(len(seen) == 29, "developer_inventory_count")
    marker = host("/opt/alfred-developer-v1/active")
    read(marker, uid=os.geteuid())
    require(stat.S_IMODE(marker.stat().st_mode) == 0o644, "activation_marker_mode")
    policy = host("/etc/alfred-fresh-v1/policy.json")
    data = json.loads(read(policy, uid=os.geteuid(), private=True))
    require(
        stat.S_IMODE(policy.stat().st_mode) == 0o600
        and data["enabled"] is True
        and data["project"] == "dev-v1-accept"
        and data["destination"] == "hrsnyde1/alfred-dev-v1-acceptance",
        "active_policy_contract",
    )


def snapshot(ctx):
    paths = {
        host(PLAN),
        host(ctx["spec_path"]),
        host("/opt/alfred-developer-v1/active"),
        host("/etc/alfred-fresh-v1/policy.json"),
        host("/home/alfred/Alfred/gateway/v1-1-intake.json"),
    }
    for name in ("/var/lib/alfred-v1-handoffs", GRANTS):
        for p in host(name).rglob("*"):
            require(not p.is_symlink(), "evidence_symlink: " + str(p))
            if not p.is_dir():
                paths.add(p)
    return "".join(
        digest(read(p)) + "  /" + str(p.relative_to(ROOT)) + "\n" for p in sorted(paths)
    ).encode()


def inspect():
    pause = host("/home/alfred/Alfred/gateway/PAUSE")
    require(
        stat.S_ISREG(pause.lstat().st_mode) and not pause.is_symlink(),
        "gateway_PAUSE_missing_or_invalid",
    )

    def check(label, operation):
        try:
            return operation()
        except Blocked:
            raise
        except (
            OSError,
            ValueError,
            KeyError,
            AttributeError,
            subprocess.SubprocessError,
        ) as exc:
            # Never print JSON bodies or subprocess output (which can contain credentials).
            raise Blocked(label + ": " + type(exc).__name__) from None

    check("worker_state", idle)
    release = check("protected_package", verify_package)
    ctx = check("T0003_and_approval_state", task_and_approvals)
    check("installed_runtime_contract", lambda: installed(release))
    return check("preservation_snapshot", lambda: snapshot(ctx))


def publish_once(path, raw):
    if os.path.lexists(path):
        require(
            read(path, uid=os.geteuid(), private=True) == raw,
            "existing_preservation_baseline_differs",
        )
        return "existing_verified"
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".preserved-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        rename = ctypes.CDLL(None, use_errno=True).renameat2
        rename.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        rename.restype = ctypes.c_int
        if (
            rename(
                directory,
                os.fsencode(temporary.name),
                directory,
                os.fsencode(path.name),
                1,
            )
            != 0
        ):
            number = ctypes.get_errno()
            raise OSError(number, "preservation publication refused")
        os.fsync(directory)
    finally:
        if temporary is not None:
            temporary.unlink(
                missing_ok=True
            )  # Only this invocation's unpublished temporary.
        os.close(directory)
    return "created"


def continue_phase_a():
    before = inspect()  # Every check precedes the first possible filesystem write.
    require(inspect() == before, "evidence_changed_during_preflight")
    state = publish_once(host(REVIEW + "/preserved.sha256"), before)
    require(inspect() == before, "evidence_changed_after_preservation")
    require(
        read(host(REVIEW + "/preserved.sha256"), uid=os.geteuid(), private=True)
        == before,
        "preservation_verification_failed",
    )
    return {
        "status": "PHASE_A_PREPARED_HELD",
        "preservation": state,
        "installation": "not_executed",
        "service_actions": "none",
        "T0003": "held",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--operator-quiescence-confirmed", action="store_true")
    args = parser.parse_args()
    require(os.geteuid() == 0, "root_operator_required")
    require(
        args.operator_quiescence_confirmed, "operator_messaging_quiescence_required"
    )
    result = continue_phase_a()
    print(json.dumps(result, sort_keys=True))
    print("PHASE_A_PREPARED_HELD")


if __name__ == "__main__":
    try:
        main()
    except (
        Blocked,
        OSError,
        ValueError,
        KeyError,
        AttributeError,
        subprocess.SubprocessError,
    ) as exc:
        detail = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
        if isinstance(exc, OSError):
            detail += f": errno={exc.errno}"
        print("BLOCKED: " + detail, file=sys.stderr)
        raise SystemExit(1) from None
