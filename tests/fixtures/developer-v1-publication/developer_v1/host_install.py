"""Transactional host opt-in; never run without separate operator authorization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import shutil
import stat
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

from . import install_config
from .router import Denied

REQUIRED_FILES = {
    "__init__.py", "approval_transition.py", "execution.py", "gateway_adapter.py",
    "host_install.py", "install_config.py", "isolated_apply.py", "owner_grants.py",
    "pipeline.py", "real_worker.py", "router.py", "run_task.py", "stage_approval.py",
    "publication_approval.py", "stage_publication.py",
    "specialists.json", "models.codex-verified.example.json",
    "alfred-development-intake-v1.conf", "schemas/model-edits.schema.json",
}


@dataclass(frozen=True)
class Layout:
    staging: Path
    release_parent: Path
    grant_root: Path
    worktree_root: Path
    state_root: Path
    dropin: Path
    intake_source: Path
    intake_config: Path
    gateway_root: Path
    registry: Path
    runner_uid: int
    runner_gid: int


def live_layout(staging: Path) -> Layout:
    user = pwd.getpwnam("alfred")
    return Layout(staging, Path("/opt/alfred-developer-v1"),
        Path("/var/lib/alfred-development-grants"),
        Path("/var/lib/alfred-development-worktrees"),
        Path("/var/lib/alfred-development-state"),
        Path("/etc/systemd/system/alfred-development-intake.service.d/30-developer-v1.conf"),
        Path("/usr/local/lib/alfred-v1.1/trusted_intake.py"),
        Path("/home/alfred/Alfred/gateway/v1-1-intake.json"),
        Path("/home/alfred/Git/alfred"),
        Path("/home/alfred/Git/alfred/registry/projects.yaml"),
        user.pw_uid, user.pw_gid)


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verified_release(staging: Path, manifest_sha256: str) -> dict[str, bytes]:
    manifest = staging / "developer_v1" / "release.sha256"
    raw = manifest.read_bytes()
    if _hash(raw) != manifest_sha256:
        raise Denied("release manifest digest mismatch")
    files = {}
    for line in raw.decode().splitlines():
        digest, separator, relative = line.partition("  ")
        path = Path(relative)
        if (separator != "  " or len(digest) != 64 or not relative.startswith("developer_v1/")
                or path.is_absolute() or ".." in path.parts or relative in files):
            raise Denied("release manifest invalid")
        source = staging / path
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 131072:
            raise Denied("release contains unsupported file")
        data = source.read_bytes()
        if _hash(data) != digest:
            raise Denied("staged release file digest mismatch")
        files[relative] = data
    if "developer_v1/HOST_ACCEPTANCE.md" in files:
        raise Denied("host procedure must remain outside the pinned executable release")
    actual = set()
    for path in (staging / "developer_v1").rglob("*"):
        if path.is_symlink():
            raise Denied("symlink in staged release")
        if path.is_file():
            relative = str(path.relative_to(staging))
            if relative != "developer_v1/HOST_ACCEPTANCE.md":
                actual.add(relative)
    if actual != set(files) | {"developer_v1/release.sha256"}:
        raise Denied("staged release has unlisted or missing files")
    if not REQUIRED_FILES <= {str(Path(name).relative_to("developer_v1")) for name in files}:
        raise Denied("release manifest incomplete")
    return files


def _private_dir(path: Path, uid: int, gid: int) -> None:
    if not path.exists():
        path.mkdir(mode=0o700)
        if os.geteuid() == 0:
            os.chown(path, uid, gid)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != uid
            or info.st_gid != gid or stat.S_IMODE(info.st_mode) != 0o700):
        raise Denied("host private directory mismatch")


def _release_dir(path: Path) -> None:
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_gid != os.getegid() or info.st_mode & 0o022):
        raise Denied("installation directory ownership or mode invalid")


def _write_once(path: Path, data: bytes, uid: int, gid: int, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        if os.geteuid() == 0:
            os.fchown(stream.fileno(), uid, gid)
        os.fchmod(stream.fileno(), mode)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _existing_file(path: Path, data: bytes, uid: int, gid: int, mode: int) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != uid or info.st_gid != gid
            or stat.S_IMODE(info.st_mode) != mode or path.read_bytes() != data):
        raise Denied("existing installation artifact differs from reviewed release")
    return True


def _existing_release(path: Path, files: dict[str, bytes], manifest: bytes,
                      uid: int, gid: int) -> bool:
    if not path.exists() and not path.is_symlink():
        return False
    if path.is_symlink() or not path.is_dir():
        raise Denied("existing release is not a directory")
    expected = {str(Path(name).relative_to("developer_v1")): data
                for name, data in files.items()}
    expected["release.sha256"] = manifest
    actual = set()
    for item in (path, *path.rglob("*")):
        if item.is_symlink():
            raise Denied("existing release contains symlink")
        info = item.lstat()
        if (info.st_uid != uid or info.st_gid != gid
                or stat.S_IMODE(info.st_mode) & 0o022):
            raise Denied("existing release ownership or mode invalid")
        if item.is_file():
            relative = str(item.relative_to(path))
            actual.add(relative)
            _existing_file(item, expected.get(relative, b""), uid, gid, 0o644)
    if actual != set(expected):
        raise Denied("existing release file set differs from reviewed release")
    return True


class Systemd:
    def daemon_reload(self) -> None:
        subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=20)

    def restart_intake(self) -> None:
        subprocess.run(["systemctl", "restart", "alfred-development-intake.service"],
                       check=True, timeout=40)

    def healthy(self) -> bool:
        for service in ("alfred-development-intake.service", "alfred-photon.service",
                        "alfred-hermes.service"):
            result = subprocess.run(["systemctl", "is-active", "--quiet", service],
                                    timeout=10, check=False)
            if result.returncode:
                return False
        return True

    def gateway_state(self) -> tuple[str, str]:
        return tuple(subprocess.check_output(
            ["systemctl", "show", "-p", "ActiveState", "-p", "Result", unit],
            text=True, timeout=10) for unit in
            ("alfred-development-gateway.service", "alfred-development-gateway.timer"))


class HostPermissionProbe:
    """Root-only DAC check using the actual host identities before activation."""

    @staticmethod
    def _can(uid: int, gid: int, path: Path, operation: str) -> bool:
        script = ("import os,sys\n"
                  "if os.geteuid()!=int(sys.argv[3]) or os.getegid()!=int(sys.argv[4]): sys.exit(77)\n"
                  "try:\n"
                  " p=sys.argv[1]; op=sys.argv[2]\n"
                  " open(p,'rb').close() if op=='read' else os.listdir(p)\n"
                  "except PermissionError: sys.exit(13)\n")
        result = subprocess.run(["/usr/bin/setpriv", "--reuid", str(uid),
            "--regid", str(gid), "--init-groups", "/usr/bin/python3", "-I", "-c",
            script, str(path), operation, str(uid), str(gid)], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=10, check=False)
        if result.returncode not in (0, 13):
            raise Denied("host identity switch or permission probe failed")
        return result.returncode == 0

    @staticmethod
    def _require_root() -> None:
        if os.geteuid() != 0:
            raise Denied("real UID permission preflight requires administrator")

    def verify(self, layout: Layout) -> dict:
        self._require_root()
        candidate = layout.state_root / f".permission-probe-{uuid.uuid4().hex}.json"
        _write_once(candidate, b'{"authorization_reference":"fixture-only"}\n',
                    layout.runner_uid, layout.runner_gid, 0o600)
        try:
            checks = {"runner_request": "PASS" if self._can(
                layout.runner_uid, layout.runner_gid, candidate, "read") else "FAIL"}
            protected = {
                "request": (candidate, "read"),
                "grant_store": (layout.grant_root, "list"),
                "gateway_repository": (layout.gateway_root, "list"),
                "gateway_registry": (layout.registry, "read"),
                "intake_config": (layout.intake_config, "read"),
            }
            gateway_state = layout.intake_config.parent
            for label, path in {
                "gateway_journal": gateway_state / "journal.jsonl",
                "cto_delivery": gateway_state / "v1-cto-delivery.json",
                "cto_plans": gateway_state / "cto-plans",
            }.items():
                if path.exists():
                    protected[label] = (path, "list" if path.is_dir() else "read")
            auth = Path("/home/alfred/.codex/auth.json")
            if auth.exists():
                protected["provider_auth"] = (auth, "read")
            if layout.grant_root.exists():
                for grant in layout.grant_root.glob("grant-*.json"):
                    protected[f"grant_record:{grant.name}"] = (grant, "read")
            for account in ("alfreddev", "alfredmsg", "alfredphoton"):
                user = pwd.getpwnam(account)
                checks[account] = {name: "FAIL" if self._can(
                    user.pw_uid, user.pw_gid, path, operation) else "PASS"
                    for name, (path, operation) in protected.items()}
            if checks["runner_request"] != "PASS" or any(
                    result == "FAIL" for account in ("alfreddev", "alfredmsg", "alfredphoton")
                    for result in checks[account].values()):
                raise PermissionFailure(checks)
            return checks
        finally:
            candidate.unlink()


class PermissionFailure(Denied):
    def __init__(self, checks: dict):
        self.checks = checks
        super().__init__("host permission preflight failed")


def preflight(layout: Layout, manifest_sha256: str, *, systemd=None,
              permissions=None, temp_parent: Path = Path("/tmp")) -> dict:
    """Read-only host checks plus a disposable DAC fixture; no activation."""
    systemd = systemd or Systemd()
    permissions = permissions or HostPermissionProbe()
    files = verified_release(layout.staging, manifest_sha256)
    install_config._reviewed_source(layout.intake_source)
    install_config._regular(layout.intake_config, 4096, owner=layout.runner_uid,
                            mode=0o600)
    if not layout.registry.is_file():
        raise Denied("Gateway registry unavailable")
    if not systemd.healthy():
        raise Denied("Alfred Intake, Photon or Hermes service unhealthy")
    gateway = systemd.gateway_state()
    if any("Result=failed" in state or "ActiveState=failed" in state for state in gateway):
        raise Denied("Gateway service or timer failed")
    cto_file = layout.gateway_root / ".dev" / "bin" / "cto.py"
    cto_digest = _hash(cto_file.read_bytes())
    identities = {name: pwd.getpwnam(name) for name in
                  ("alfred", "alfreddev", "alfredmsg", "alfredphoton")}
    if (identities["alfred"].pw_uid != layout.runner_uid
            or identities["alfred"].pw_gid != layout.runner_gid
            or len({user.pw_uid for user in identities.values()}) != len(identities)):
        raise Denied("required host Linux identities do not match")
    for path in (layout.grant_root, layout.state_root, layout.worktree_root):
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != layout.runner_uid
                    or info.st_gid != layout.runner_gid
                    or stat.S_IMODE(info.st_mode) != 0o700):
                raise Denied(f"existing private directory permissions invalid: {path}")
    with tempfile.TemporaryDirectory(prefix="alfred-developer-v1-preflight-",
                                     dir=temp_parent) as temporary:
        root = Path(temporary)
        # Permit traversal to the known fixture paths, never directory listing.
        root.chmod(0o711)
        state = root / "state"
        grant = layout.grant_root if layout.grant_root.exists() else root / "grants"
        _private_dir(state, layout.runner_uid, layout.runner_gid)
        if grant != layout.grant_root:
            _private_dir(grant, layout.runner_uid, layout.runner_gid)
        checked = replace(layout, state_root=state, grant_root=grant)
        checks = permissions.verify(checked)
    return {"state": "PASS", "checks": checks,
            "services": "PASS", "gateway": list(gateway),
            "cto_sha256": cto_digest,
            "identities": {name: user.pw_uid for name, user in identities.items()},
            "release_files": len(files), "manifest_sha256": manifest_sha256}


def install(layout: Layout, manifest_sha256: str, *, systemd=None, permissions=None) -> dict:
    """Copy a hash-pinned release, opt in Intake, restart once; rollback on failure."""
    systemd = systemd or Systemd()
    permissions = permissions or HostPermissionProbe()
    if not systemd.healthy():
        raise Denied("existing Alfred services are not healthy")
    gateway_before = systemd.gateway_state()
    cto_file = layout.gateway_root / ".dev" / "bin" / "cto.py"
    cto_before = _hash(cto_file.read_bytes())
    install_config._reviewed_source(layout.intake_source)
    files = verified_release(layout.staging, manifest_sha256)
    final = layout.release_parent / "developer_v1"
    marker = layout.release_parent / "active"
    if marker.exists() or marker.is_symlink():
        raise Denied("development activation marker already exists")
    manifest = (layout.staging / "developer_v1" / "release.sha256").read_bytes()
    release_present = _existing_release(final, files, manifest, os.geteuid(), os.getegid())
    dropin_data = files["developer_v1/alfred-development-intake-v1.conf"]
    dropin_present = _existing_file(layout.dropin, dropin_data,
                                    os.geteuid(), os.getegid(), 0o644)
    model_path = layout.state_root / "models.json"
    model_data = files["developer_v1/models.codex-verified.example.json"]
    model_present = _existing_file(model_path, model_data,
                                   layout.runner_uid, layout.runner_gid, 0o600)
    temp = layout.release_parent / f".developer_v1-{uuid.uuid4().hex}"
    created = {"release": False, "model": False, "dropin": False,
               "config": False, "restarted": False}
    try:
        layout.release_parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        _release_dir(layout.release_parent)
        for path in (layout.grant_root, layout.worktree_root, layout.state_root):
            _private_dir(path, layout.runner_uid, layout.runner_gid)
        permissions.verify(layout)
        if not release_present:
            temp.mkdir(mode=0o755)
            for relative, data in files.items():
                target = temp / Path(relative).relative_to("developer_v1")
                target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                _write_once(target, data, os.geteuid(), os.getegid(), 0o644)
            _write_once(temp / "release.sha256", manifest,
                        os.geteuid(), os.getegid(), 0o644)
            _existing_release(temp, files, manifest, os.geteuid(), os.getegid())
            os.replace(temp, final)
            created["release"] = True
        if not model_present:
            _write_once(model_path, model_data, layout.runner_uid, layout.runner_gid, 0o600)
            created["model"] = True
        layout.dropin.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        _release_dir(layout.dropin.parent)
        if not dropin_present:
            _write_once(layout.dropin, dropin_data, os.geteuid(), os.getegid(), 0o644)
            created["dropin"] = True
        install_config.install(layout.intake_config, intake_source=layout.intake_source,
            grant_root=layout.grant_root, gateway_root=layout.gateway_root,
            registry=layout.registry)
        created["config"] = True
        systemd.daemon_reload()
        created["restarted"] = True
        systemd.restart_intake()
        if (not systemd.healthy() or systemd.gateway_state() != gateway_before
                or _hash(cto_file.read_bytes()) != cto_before):
            raise Denied("Alfred service health check failed after Intake restart")
        _write_once(marker, b"enabled\n", os.geteuid(), os.getegid(), 0o644)
        return {"state": "installed", "release": str(final),
                "config_backup": str(layout.intake_config) + ".pre-developer-v1"}
    except Exception:
        if marker.exists():
            marker.unlink()
        # Preserve the reviewed package and drop-in. The currently installed
        # Intake source imports this package at module load, even when the
        # development issuer is disabled in config.
        try:
            config_has_development = all(key in json.loads(layout.intake_config.read_bytes())
                                         for key in install_config.FIELDS)
        except (OSError, ValueError):
            config_has_development = False
        if created["config"] or config_has_development:
            install_config.rollback(layout.intake_config)
        if temp.exists():
            shutil.rmtree(temp)
        if created["restarted"]:
            systemd.daemon_reload()
            systemd.restart_intake()
        raise


def rollback(layout: Layout, *, systemd=None) -> dict:
    systemd = systemd or Systemd()
    marker = layout.release_parent / "active"
    if marker.exists():
        marker.unlink()
    gateway_before = systemd.gateway_state()
    cto_file = layout.gateway_root / ".dev" / "bin" / "cto.py"
    cto_before = _hash(cto_file.read_bytes())
    install_config.rollback(layout.intake_config)
    systemd.daemon_reload()
    systemd.restart_intake()
    if (not systemd.healthy() or systemd.gateway_state() != gateway_before
            or _hash(cto_file.read_bytes()) != cto_before):
        raise Denied("Alfred services unhealthy after rollback")
    return {"state": "rolled_back", "config_backup": str(layout.intake_config) + ".pre-developer-v1"}


def main() -> None:
    if os.geteuid() != 0:
        raise PermissionError("administrator required")
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--preflight", action="store_true")
    action.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    layout = live_layout(args.staging)
    if args.preflight:
        try:
            result = preflight(layout, args.manifest_sha256)
        except PermissionFailure as exc:
            print(json.dumps({"state": "FAIL", "checks": exc.checks}, sort_keys=True))
            raise SystemExit(1) from None
        except (Denied, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            print(json.dumps({"state": "FAIL", "reason": str(exc)}, sort_keys=True))
            raise SystemExit(1) from None
    else:
        result = rollback(layout) if args.rollback else install(layout, args.manifest_sha256)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
