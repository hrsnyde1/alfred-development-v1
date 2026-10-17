import hashlib
import io
import json
import os
import pwd
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from developer_v1 import host_install, install_config
from developer_v1.owner_grants import ProtectedDevelopmentAuthority
from developer_v1.real_worker import _sandbox_base
from developer_v1.router import Denied
from developer_v1.run_task import _protected_json


def _original_reviewed_intake():
    """Keep the initial installer's historical source pin separate from upgrades."""
    reviewed = (Path(__file__).parent / "fixtures/developer-v1-publication/developer_v1" /
                "trusted_intake_development.py").read_bytes()
    if hashlib.sha256(reviewed).hexdigest() != install_config.EXPECTED_INTAKE_SHA256:
        raise AssertionError("reviewed Intake source drifted")
    return reviewed


class HostInstallContract(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="alfred-host-v1-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.config = self.root / "intake.json"
        self.original = b'{"sidecar_token":"fixture-only","owner_sender_id":"owner","unknown_existing_field":42}\n'
        self.config.write_bytes(self.original)
        self.config.chmod(0o600)
        self.source = self.root / "trusted_intake.py"
        # The original installer pins the pre-evidence Intake source. The
        # currently installed source includes a separately reviewed update.
        self.reviewed_source = _original_reviewed_intake()
        self.source.write_bytes(self.reviewed_source)
        self.grants = self.root / "grants"
        self.grants.mkdir(mode=0o700)
        self.gateway = self.root / "gateway"
        self.gateway.mkdir()
        self.registry = self.gateway / "projects.yaml"
        self.registry.write_text("fixture")

    def install(self):
        return install_config.install(self.config, intake_source=self.source,
                   grant_root=self.grants, gateway_root=self.gateway, registry=self.registry)

    def test_historical_intake_fixture_is_exactly_reviewed_copy(self):
        self.assertEqual(self.source.read_bytes(), self.reviewed_source)
        self.assertEqual(hashlib.sha256(self.reviewed_source).hexdigest(),
                         install_config.EXPECTED_INTAKE_SHA256)

    def test_config_backup_is_verified_and_rollback_restores_exact_bytes(self):
        self.assertEqual(self.install()["state"], "installed")
        backup = self.root / "intake.json.pre-developer-v1"
        self.assertEqual(backup.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o600)
        self.assertEqual(backup.stat().st_uid, self.config.stat().st_uid)
        updated = json.loads(self.config.read_bytes())
        self.assertEqual({k: updated[k] for k in ("sidecar_token", "owner_sender_id", "unknown_existing_field")},
                         json.loads(self.original))
        self.assertEqual(set(updated) - set(json.loads(self.original)), set(install_config.FIELDS))
        self.assertEqual(self.install()["state"], "already_installed")
        self.assertEqual(install_config.rollback(self.config)["state"], "rolled_back")
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)

    def test_partial_failure_keeps_original_and_valid_backup(self):
        with patch.object(install_config, "_replace", side_effect=OSError("fixture failure")):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual((self.root / "intake.json.pre-developer-v1").read_bytes(), self.original)
        self.assertEqual(self.install()["state"], "installed")

    def test_drifted_source_and_backup_are_refused(self):
        self.source.write_text("changed")
        with self.assertRaises(Denied):
            self.install()
        self.assertEqual(self.config.read_bytes(), self.original)
        self.source.write_bytes(self.reviewed_source)
        backup = self.root / "intake.json.pre-developer-v1"
        backup.write_text("forged")
        backup.chmod(0o600)
        with self.assertRaises(Denied):
            self.install()
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_rollback_rejects_unrelated_config_change(self):
        self.install()
        value = json.loads(self.config.read_text())
        value["owner_sender_id"] = "changed"
        self.config.write_text(json.dumps(value))
        self.config.chmod(0o600)
        with self.assertRaises(Denied):
            install_config.rollback(self.config)

    def test_real_runner_uid_and_private_request_contract(self):
        self.assertEqual(os.geteuid(), pwd.getpwnam("alfred").pw_uid)
        self.assertNotEqual(pwd.getpwnam("alfreddev").pw_uid, os.geteuid())
        private = self.root / "private"
        private.mkdir(mode=0o700)
        request = private / "request.json"
        request.write_text('{"authorization_reference":"fixture-ref"}')
        request.chmod(0o600)
        self.assertEqual(_protected_json(request, 4096)["authorization_reference"], "fixture-ref")
        request.chmod(0o640)
        with self.assertRaises(Denied):
            _protected_json(request, 4096)
        request.chmod(0o600)
        private.chmod(0o750)
        with self.assertRaises(Denied):
            _protected_json(request, 4096)
        private.chmod(0o700)
        link = private / "linked.json"
        link.symlink_to(request)
        with self.assertRaises(OSError):
            _protected_json(link, 4096)

    def test_host_grants_require_root_owned_activation_marker(self):
        authority = ProtectedDevelopmentAuthority(self.grants)
        authority.activation_marker = self.root / "active"
        with self.assertRaises(Denied):
            authority.verify("0" * 32, {})
        authority.activation_marker.write_text("enabled\n")
        authority.activation_marker.chmod(0o644)
        with self.assertRaises(Denied):
            authority.verify("0" * 32, {})

    def test_os_namespace_can_write_only_bound_worktree(self):
        worktree = self.root / "worktree"
        worktree.mkdir()
        grants = self.root / "grant.json"
        grants.write_text("grant")
        gateway = self.root / "gateway-authority.json"
        gateway.write_text("authority")
        other = self.root / "other-repo.txt"
        other.write_text("other")
        paths = [str(grants), str(gateway), str(other),
                 "/home/alfred/.codex/auth.json",
                 "/usr/local/lib/alfred-v1.1/trusted_intake.py",
                 "/etc/systemd/system/alfred-development-intake.service"]
        code = ("import json,os,sys; p=json.load(sys.stdin); "
                "denied=[]; "
                "exec('for x in p:\\n try:\\n  open(x,\"a\").write(\"BAD\")\\n except OSError:\\n  denied.append(x)'); "
                "open('/workspace/allowed.txt','w').write('allowed'); "
                "print(json.dumps(denied))")
        command = [*_sandbox_base(worktree, writable=True), "/usr/bin/python3", "-c", code]
        proc = subprocess.run(command, input=json.dumps(paths), text=True,
                              capture_output=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), paths)
        self.assertEqual((worktree / "allowed.txt").read_text(), "allowed")
        self.assertEqual(grants.read_text(), "grant")
        self.assertEqual(gateway.read_text(), "authority")
        self.assertEqual(other.read_text(), "other")

    def _layout(self):
        cto = self.gateway / ".dev" / "bin"
        cto.mkdir(parents=True)
        (cto / "cto.py").write_text("fixture CTO")
        staging = self.root / "verified-staging"
        shutil.copytree(Path(__file__).parents[1] / "developer_v1",
                        staging / "developer_v1",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        return host_install.Layout(
            staging=staging, release_parent=self.root / "release",
            grant_root=self.grants, worktree_root=self.root / "worktrees",
            state_root=self.root / "state", dropin=self.root / "units" / "30-developer-v1.conf",
            intake_source=self.source, intake_config=self.config, gateway_root=self.gateway,
            registry=self.registry, runner_uid=os.geteuid(), runner_gid=os.getegid())

    def test_transactional_install_and_rollback_with_fake_service(self):
        layout = self._layout()
        manifest = layout.staging / "developer_v1" / "release.sha256"
        controller = FakeSystemd()
        result = host_install.install(layout, hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                      systemd=controller, permissions=FakePermissions())
        self.assertEqual(result["state"], "installed")
        self.assertEqual(controller.restarts, 1)
        self.assertTrue(layout.dropin.exists())
        self.assertTrue((layout.release_parent / "active").exists())
        self.assertTrue((layout.release_parent / "developer_v1" / "router.py").exists())
        self.assertEqual(stat.S_IMODE((layout.state_root / "models.json").stat().st_mode), 0o600)
        self.assertEqual(host_install.rollback(layout, systemd=controller)["state"], "rolled_back")
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(controller.restarts, 2)
        self.assertFalse((layout.release_parent / "active").exists())
        # Retained because the currently installed Intake imports developer_v1.
        self.assertTrue(layout.dropin.exists())

    def test_restart_failure_disables_grants_and_restores_intake(self):
        layout = self._layout()
        manifest = layout.staging / "developer_v1" / "release.sha256"
        controller = FakeSystemd(fail_first_restart=True)
        with self.assertRaises(OSError):
            host_install.install(layout, hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                 systemd=controller, permissions=FakePermissions())
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(controller.restarts, 2)
        self.assertFalse((layout.release_parent / "active").exists())
        self.assertTrue(layout.dropin.exists())
        self.assertTrue((layout.release_parent / "developer_v1" / "router.py").exists())

    def test_uid_preflight_failure_stops_before_config_or_restart(self):
        layout = self._layout()
        manifest = layout.staging / "developer_v1" / "release.sha256"
        controller = FakeSystemd()
        class RefusePermissions:
            def verify(self, unused):
                raise Denied("fixture host UID mismatch")
        with self.assertRaises(Denied):
            host_install.install(layout, hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                 systemd=controller, permissions=RefusePermissions())
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(controller.restarts, 0)

    def test_partial_install_can_resume_only_with_matching_artifacts(self):
        layout = self._layout()
        digest = hashlib.sha256((layout.staging / "developer_v1" /
                                 "release.sha256").read_bytes()).hexdigest()
        controller = FakeSystemd()
        with patch.object(install_config, "install", side_effect=OSError("fixture config failure")):
            with self.assertRaises(OSError):
                host_install.install(layout, digest, systemd=controller,
                                     permissions=FakePermissions())
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(controller.restarts, 0)
        self.assertFalse((layout.release_parent / "active").exists())
        self.assertEqual(host_install.install(layout, digest, systemd=controller,
                                              permissions=FakePermissions())["state"], "installed")
        self.assertEqual(controller.restarts, 1)

    def test_unlisted_or_changed_release_is_rejected_before_restart(self):
        layout = self._layout()
        digest = hashlib.sha256((layout.staging / "developer_v1" /
                                 "release.sha256").read_bytes()).hexdigest()
        controller = FakeSystemd()
        (layout.staging / "developer_v1" / "unlisted.py").write_text("unsafe")
        with self.assertRaises(Denied):
            host_install.install(layout, digest, systemd=controller,
                                 permissions=FakePermissions())
        (layout.staging / "developer_v1" / "unlisted.py").unlink()
        (layout.staging / "developer_v1" / "router.py").write_text("tampered")
        with self.assertRaises(Denied):
            host_install.install(layout, digest, systemd=controller,
                                 permissions=FakePermissions())
        self.assertEqual(controller.restarts, 0)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_standalone_preflight_passes_without_host_changes(self):
        layout = self._layout()
        digest = hashlib.sha256((layout.staging / "developer_v1" /
                                 "release.sha256").read_bytes()).hexdigest()
        controller = FakeSystemd()
        original_grants = list(self.grants.iterdir())
        def access(uid, gid, path, operation):
            return (uid == layout.runner_uid and operation == "read"
                    and path.name.startswith(".permission-probe-"))
        with patch.object(host_install.HostPermissionProbe, "_require_root"), \
             patch.object(host_install.HostPermissionProbe, "_can", side_effect=access):
            result = host_install.preflight(layout, digest, systemd=controller,
                                            temp_parent=self.root)
        self.assertEqual(result["state"], "PASS")
        self.assertEqual(result["checks"]["runner_request"], "PASS")
        for account in ("alfreddev", "alfredmsg", "alfredphoton"):
            self.assertTrue(all(value == "PASS" for value in
                                result["checks"][account].values()))
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(list(self.grants.iterdir()), original_grants)
        self.assertEqual(controller.restarts, 0)
        self.assertFalse(layout.dropin.exists())
        self.assertFalse((layout.release_parent / "active").exists())
        self.assertFalse(list(self.root.glob("alfred-developer-v1-preflight-*")))

    def test_standalone_preflight_reports_denied_identity_and_credentials(self):
        layout = self._layout()
        digest = hashlib.sha256((layout.staging / "developer_v1" /
                                 "release.sha256").read_bytes()).hexdigest()
        blocked_uid = pwd.getpwnam("alfreddev").pw_uid
        def access(uid, gid, path, operation):
            return ((uid == layout.runner_uid and path.name.startswith(".permission-probe-"))
                    or (uid == blocked_uid and path.name == "auth.json"))
        with patch.object(host_install.HostPermissionProbe, "_require_root"), \
             patch.object(host_install.HostPermissionProbe, "_can", side_effect=access):
            with self.assertRaises(host_install.PermissionFailure) as raised:
                host_install.preflight(layout, digest, systemd=FakeSystemd(),
                                       temp_parent=self.root)
        self.assertEqual(raised.exception.checks["alfreddev"]["provider_auth"], "FAIL")
        self.assertEqual(raised.exception.checks["alfredmsg"]["provider_auth"], "PASS")
        self.assertFalse(list(self.root.glob("alfred-developer-v1-preflight-*")))
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_interrupted_standalone_preflight_cleans_fixture(self):
        layout = self._layout()
        digest = hashlib.sha256((layout.staging / "developer_v1" /
                                 "release.sha256").read_bytes()).hexdigest()
        with patch.object(host_install.HostPermissionProbe, "_require_root"), \
             patch.object(host_install.HostPermissionProbe, "_can",
                          side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                host_install.preflight(layout, digest, systemd=FakeSystemd(),
                                       temp_parent=self.root)
        self.assertFalse(list(self.root.glob("alfred-developer-v1-preflight-*")))
        self.assertEqual(list(self.grants.iterdir()), [])
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_preflight_rejects_existing_unprotected_directory_without_changing_it(self):
        layout = self._layout()
        layout.state_root.mkdir(mode=0o755)
        digest = hashlib.sha256((layout.staging / "developer_v1" /
                                 "release.sha256").read_bytes()).hexdigest()
        before = stat.S_IMODE(layout.state_root.stat().st_mode)
        with self.assertRaises(Denied):
            host_install.preflight(layout, digest, systemd=FakeSystemd(),
                                   temp_parent=self.root)
        self.assertEqual(stat.S_IMODE(layout.state_root.stat().st_mode), before)
        self.assertFalse(list(self.root.glob("alfred-developer-v1-preflight-*")))

    def test_preflight_requires_healthy_services_and_all_host_identities(self):
        layout = self._layout()
        digest = hashlib.sha256((layout.staging / "developer_v1" /
                                 "release.sha256").read_bytes()).hexdigest()
        unhealthy = FakeSystemd()
        unhealthy.healthy = lambda: False
        with self.assertRaises(Denied):
            host_install.preflight(layout, digest, systemd=unhealthy,
                                   temp_parent=self.root)
        real_lookup = pwd.getpwnam
        def missing_photon(name):
            if name == "alfredphoton":
                raise KeyError(name)
            return real_lookup(name)
        with patch.object(host_install.pwd, "getpwnam", side_effect=missing_photon):
            with self.assertRaises(KeyError):
                host_install.preflight(layout, digest, systemd=FakeSystemd(),
                                       temp_parent=self.root)
        self.assertFalse(list(self.root.glob("alfred-developer-v1-preflight-*")))
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_preflight_and_rollback_cli_options_are_exclusive(self):
        with patch.object(host_install.os, "geteuid", return_value=0), \
             patch("sys.argv", ["host_install", "--staging", "/tmp/stage",
                                 "--manifest-sha256", "0" * 64,
                                 "--preflight", "--rollback"]), \
             patch("sys.stderr"):
            with self.assertRaises(SystemExit) as raised:
                host_install.main()
        self.assertEqual(raised.exception.code, 2)

    def test_preflight_cli_reports_pass_and_fail(self):
        args = ["host_install", "--staging", "/tmp/stage",
                "--manifest-sha256", "0" * 64, "--preflight"]
        output = io.StringIO()
        with patch.object(host_install.os, "geteuid", return_value=0), \
             patch("sys.argv", args), patch("sys.stdout", output), \
             patch.object(host_install, "preflight", return_value={"state": "PASS",
                           "checks": {"runner_request": "PASS"}}):
            host_install.main()
        self.assertEqual(json.loads(output.getvalue())["state"], "PASS")
        output = io.StringIO()
        with patch.object(host_install.os, "geteuid", return_value=0), \
             patch("sys.argv", args), patch("sys.stdout", output), \
             patch.object(host_install, "preflight", side_effect=host_install.PermissionFailure(
                           {"runner_request": "FAIL"})):
            with self.assertRaises(SystemExit) as raised:
                host_install.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(json.loads(output.getvalue())["checks"]["runner_request"], "FAIL")

    def test_permission_probe_distinguishes_denial_from_identity_switch_failure(self):
        with patch.object(host_install.subprocess, "run",
                          return_value=SimpleNamespace(returncode=13)):
            self.assertFalse(host_install.HostPermissionProbe._can(
                990, 984, self.config, "read"))
        with patch.object(host_install.subprocess, "run",
                          return_value=SimpleNamespace(returncode=77)):
            with self.assertRaises(Denied):
                host_install.HostPermissionProbe._can(990, 984, self.config, "read")


class FakeSystemd:
    def __init__(self, fail_first_restart=False):
        self.restarts = 0
        self.fail_first_restart = fail_first_restart

    def healthy(self):
        return True

    def gateway_state(self):
        return ("gateway-service-inactive-success", "gateway-timer-inactive-success")

    def daemon_reload(self):
        pass

    def restart_intake(self):
        self.restarts += 1
        if self.fail_first_restart and self.restarts == 1:
            raise OSError("fixture restart failure")


class FakePermissions:
    def verify(self, layout):
        assert stat.S_IMODE(layout.state_root.stat().st_mode) == 0o700
        assert stat.S_IMODE(layout.grant_root.stat().st_mode) == 0o700


if __name__ == "__main__":
    unittest.main()
