from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

from task_a.evidence import copy_into_isolated_root, verify_plugin
from task_a.release import ReleaseError


SOURCE = Path("/home/alfred/.hermes/plugins/alfred_development_status")


def test_installed_evidence_bridge_v021_inventory_is_read_only():
    observed = verify_plugin(SOURCE)
    assert set(observed) == {"__init__.py", "plugin.yaml", "development_evidence_bridge.py", "hermes_development_status_bridge.py"}


def test_isolated_evidence_copy_preserves_both_read_only_tool_registrations(lab_root):
    target = lab_root / "runtime/plugins/alfred_development_status"
    copy_into_isolated_root(lab_root, SOURCE, target)
    assert verify_plugin(target) == verify_plugin(SOURCE)
    spec = importlib.util.spec_from_file_location("staged_task_a_evidence", target / "__init__.py", submodule_search_locations=[str(target)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        registrations = []
        class Context:
            def register_tool(self, **kwargs):
                registrations.append(kwargs)
        module.register(Context())
        assert {r["name"] for r in registrations} == {"development_task_status", "development_evidence_status"}
        assert {r["toolset"] for r in registrations} == {"alfred_development_status"}
        assert all(r["schema"]["parameters"]["additionalProperties"] is False for r in registrations)
        assert module.development_evidence_status({"execute": True}) == '{"ok": false, "error": "development_evidence_unavailable"}'
    finally:
        for key in list(sys.modules):
            if key == spec.name or key.startswith(spec.name + "."):
                del sys.modules[key]


def test_evidence_copy_refuses_changed_source(lab_root):
    fake = lab_root / "modified-plugin"
    copy_into_isolated_root(lab_root, SOURCE, fake)
    (fake / "plugin.yaml").write_text("changed\n")
    with pytest.raises(ReleaseError, match="checksum"):
        verify_plugin(fake)
