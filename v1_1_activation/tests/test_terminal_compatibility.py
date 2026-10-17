"""Staging checks for the existing Hermes local terminal migration option.

These checks run as the staging UID. The proposed alfredmsg/systemd boundary
requires the separate host acceptance in OPERATOR_MINIMAL_MIGRATION.md.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TASK_A = Path(__file__).resolve().parents[2]
UNIT = TASK_A / "v1_1_activation/units/alfred-hermes.service"
HERMES_SOURCE = Path("/home/alfred/.hermes/hermes-agent")


class TerminalCompatibilityTest(unittest.TestCase):
    def test_service_selects_local_without_docker_authority(self):
        unit = UNIT.read_text()
        self.assertIn("User=alfredmsg\n", unit)
        self.assertIn("Environment=TERMINAL_ENV=local\n", unit)
        self.assertIn("WorkingDirectory=/var/lib/alfredmsg/hermes\n", unit)
        self.assertIn("ReadWritePaths=/var/lib/alfredmsg\n", unit)
        self.assertIn("ProtectSystem=strict\n", unit)
        self.assertIn("ProtectHome=read-only\n", unit)
        self.assertIn("NoNewPrivileges=yes\n", unit)
        self.assertNotIn("SupplementaryGroups=docker", unit)
        self.assertNotIn("docker.sock", unit)

    def test_pinned_local_backend_runs_command_and_private_workspace_operation(self):
        self.assertTrue(HERMES_SOURCE.is_dir(), "pinned Hermes source missing")
        with tempfile.TemporaryDirectory(prefix="v11-terminal-", dir=TASK_A) as scratch:
            env_vars = {"HERMES_HOME": scratch, "HOME": scratch, "TERMINAL_ENV": "local"}
            with patch.dict(os.environ, env_vars):
                sys.path.insert(0, str(HERMES_SOURCE))
                sys.dont_write_bytecode = True
                try:
                    from tools.environments.local import LocalEnvironment
                    from tools.terminal_tool_backends import _create_environment

                    terminal = _create_environment("local", image="", cwd=scratch, timeout=10)
                    self.assertIsInstance(terminal, LocalEnvironment)
                    result = terminal.execute("printf terminal-ok", timeout=10)
                    self.assertEqual(result["returncode"], 0, result)
                    self.assertEqual(result["output"], "terminal-ok")

                    workspace = Path(scratch, "workspace")
                    workspace.mkdir()
                    result = terminal.execute(
                        "printf workspace-ok > probe.txt && cat probe.txt && rm probe.txt && test ! -e probe.txt",
                        cwd=str(workspace), timeout=10,
                    )
                    self.assertEqual(result["returncode"], 0, result)
                    self.assertEqual(result["output"], "workspace-ok")
                    self.assertFalse((workspace / "probe.txt").exists())
                finally:
                    sys.path.remove(str(HERMES_SOURCE))


if __name__ == "__main__":
    unittest.main()
