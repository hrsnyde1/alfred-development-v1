import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("staged_intake_tool", ROOT / "plugin" / "__init__.py")
assert SPEC and SPEC.loader
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def test_model_cannot_supply_sender_event_or_project(monkeypatch):
    monkeypatch.setattr(tool, "_bound_origin", lambda: None)
    result = json.loads(tool.development_gateway_submit({}))
    assert result == {"ok": False, "error": "unbound_photon_event"}
    monkeypatch.setattr(tool, "_bound_origin", lambda: {"event_id": "sdk-1", "text_digest": "digest"})
    arguments = {field: "content" for field in tool.FIELDS}
    arguments["sender_id"] = "owner"
    arguments["company"] = "other-company"
    arguments["project_hint"] = "other-project"
    assert json.loads(tool.development_gateway_submit(arguments))["error"] == "invalid_draft"
    assert set(tool.SUBMIT_SCHEMA["parameters"]["properties"]) == set(tool.FIELDS)
    assert len(tool.SUBMIT_SCHEMA["parameters"]["properties"]) == 9
    assert tool.SUBMIT_SCHEMA["parameters"]["additionalProperties"] is False
    assert "bugfix" in tool.SUBMIT_SCHEMA["parameters"]["properties"]["task_type"]["enum"]
    assert "- [ ]" in tool.SUBMIT_SCHEMA["parameters"]["properties"]["acceptance_criteria"]["description"]


def test_submit_only_prepares_and_status_returns_protected_gateway_result(monkeypatch):
    monkeypatch.setattr(tool, "_bound_origin", lambda: {"event_id": "sdk-1", "text_digest": "digest"})
    calls = []

    def call(request):
        calls.append(request)
        if request["op"] == "submit":
            return {"ok": True, "state": "awaiting_confirmation", "request_id": "protected-id"}
        return {"ok": True, "state": "filed", "task_id": "T-0001", "project": "dev-001"}

    monkeypatch.setattr(tool, "_call", call)
    result = json.loads(tool.development_gateway_submit({field: "content" for field in tool.FIELDS}))
    assert result["state"] == "awaiting_confirmation"
    assert len(calls) == 1
    assert calls[0]["event_id"] == "sdk-1" and calls[0]["text_digest"] == "digest"
    assert json.loads(tool.development_gateway_status({}))["task_id"] == "T-0001"


def test_gateway_rejection_is_reported_without_filed_id(monkeypatch):
    monkeypatch.setattr(tool, "_bound_origin", lambda: {"event_id": "sdk-1", "text_digest": "digest"})
    monkeypatch.setattr(tool, "_call", lambda request: (
        {"ok": True, "state": "submitted", "request_id": "rid"} if request["op"] == "submit"
        else {"ok": True, "state": "rejected_invalid", "request_id": "rid"}))
    result = json.loads(tool.development_gateway_status({}))
    assert result == {"ok": True, "state": "rejected_invalid", "request_id": "rid"}
