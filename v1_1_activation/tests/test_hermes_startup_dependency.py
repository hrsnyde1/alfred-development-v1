"""Read-only source checks for the V1.1 Hermes dependency startup gate.

Run with the pinned Hermes test environment. No installer or gateway is started.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TASK_A = Path(__file__).resolve().parents[2]
SOURCE = Path('/home/alfred/.hermes/hermes-agent')
OWNER_HOME = Path('/home/alfred/.hermes')


class DependencySelectionTest(unittest.TestCase):
    def test_pinned_tool_closure_is_verified_for_private_staging(self):
        sys.path.insert(0, str(SOURCE))
        sys.dont_write_bytecode = True
        try:
            from pm.build_operations import verified_tools
            from pm.lock import Lockfile
            from pm.registry import tool_roots
            from pm.store import current_target

            names = [*tool_roots(Lockfile(SOURCE / 'pm/lock.json').names()), 'uv']
            verified = verified_tools(names, source_store=OWNER_HOME / 'tools',
                                      target=current_target())
            self.assertEqual(set(verified.entries), set(names))
        finally:
            sys.path.remove(str(SOURCE))

    def test_service_selects_private_tool_store(self):
        unit = (TASK_A / 'v1_1_activation/units/alfred-hermes.service').read_text()
        self.assertIn('Environment=HERMES_HOME=/var/lib/alfredmsg/hermes\n', unit)
        self.assertIn('Environment=HERMES_RUNTIME_DIR=/var/lib/alfredmsg/hermes/tools\n', unit)
        self.assertIn('ProtectSystem=strict\n', unit)
        self.assertIn('ReadWritePaths=/var/lib/alfredmsg\n', unit)

    def test_new_home_borrows_checkout_but_has_no_committed_environment(self):
        sys.path.insert(0, str(SOURCE))
        sys.dont_write_bytecode = True
        try:
            from pm.environments import (committed_venv, install_key,
                                         owning_home_root, runtime_facts_path)

            with tempfile.TemporaryDirectory(prefix='v11-deps-', dir=TASK_A) as scratch:
                with patch.dict(os.environ, {'HERMES_HOME': scratch}):
                    self.assertEqual(install_key(SOURCE), 'e1541360de565941')
                    self.assertEqual(owning_home_root(SOURCE), OWNER_HOME)
                    self.assertFalse(runtime_facts_path(SOURCE).exists())
                    self.assertIsNone(committed_venv(SOURCE))
        finally:
            sys.path.remove(str(SOURCE))

    def test_owner_environment_is_install_scoped(self):
        sys.path.insert(0, str(SOURCE))
        sys.dont_write_bytecode = True
        try:
            from pm.environments import committed_venv, install_state_dir

            with patch.dict(os.environ, {'HERMES_HOME': str(OWNER_HOME)}):
                installed = committed_venv(SOURCE)
                self.assertIsNotNone(installed)
                self.assertTrue(installed.is_relative_to(install_state_dir(SOURCE) / 'environments'))
                self.assertTrue((installed / 'pyvenv.cfg').is_file())
        finally:
            sys.path.remove(str(SOURCE))


if __name__ == '__main__':
    unittest.main()
