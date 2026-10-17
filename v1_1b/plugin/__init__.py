"""Staged Hermes tool: draft content only, no caller-supplied identity or path."""

import json
import os
import socket
import time

FIELDS = (
    "title", "task_type", "objective", "scope", "requirements", "constraints",
    "acceptance_criteria", "security_considerations", "testing_requirements",
)
SOCKET_ENV = "ALFRED_DEVELOPMENT_INTAKE_SOCKET"


def _bound_origin():
    try:
        from agent.delegation_context import is_delegated_child_context
        from gateway.session_context import development_intake_origin
        if is_delegated_child_context():
            return None
    except ImportError:
        return None
    return development_intake_origin()


def _call(request):
    path = os.environ.get(SOCKET_ENV, "")
    if not path or len(path) > 100:
        return {"ok": False, "error": "intake_unavailable"}
    body = (json.dumps(request, separators=(",", ":")) + "\n").encode()
    if len(body) > 64 * 1024:
        return {"ok": False, "error": "request_too_large"}
    try:
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(path)
            client.sendall(body)
            answer = bytearray()
            while len(answer) <= 4096 and b"\n" not in answer:
                chunk = client.recv(1024)
                if not chunk:
                    break
                answer.extend(chunk)
            if len(answer) > 4096 or b"\n" not in answer:
                raise ValueError("invalid response")
            result = json.loads(bytes(answer).split(b"\n", 1)[0])
            return result if isinstance(result, dict) else {"ok": False, "error": "intake_unavailable"}
    except (OSError, ValueError):
        return {"ok": False, "error": "intake_unavailable"}


def _response(result):
    return json.dumps(result, separators=(",", ":"), ensure_ascii=True)


def development_gateway_submit(arguments=None):
    origin = _bound_origin()
    if origin is None:
        return _response({"ok": False, "error": "unbound_photon_event"})
    if not isinstance(arguments, dict) or set(arguments) != set(FIELDS):
        return _response({"ok": False, "error": "invalid_draft"})
    result = _call({"op": "submit", "event_id": origin["event_id"],
                    "text_digest": origin["text_digest"], "draft": arguments})
    return _response(result)


def _status_with_brief_poll(origin):
    # Return an ID only after the protected Gateway journal records `filed`.
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        status = _call({"op": "status", "event_id": origin["event_id"],
                        "text_digest": origin["text_digest"]})
        if status.get("state") in {"filed", "rejected_invalid", "needs_clarification"} or status.get("ok") is False:
            return _response(status)
        time.sleep(0.25)
    return _response(status)


def development_gateway_status(arguments=None):
    origin = _bound_origin()
    if origin is None or arguments not in ({}, None):
        return _response({"ok": False, "error": "unbound_photon_event"})
    result = _call({"op": "status", "event_id": origin["event_id"],
                    "text_digest": origin["text_digest"]})
    return _status_with_brief_poll(origin) if result.get("state") == "submitted" else _response(result)


SUBMIT_SCHEMA = {"name": "development_gateway_submit",
                 "description": "Prepare a development request preview for the current owner's natural-language request. Filing requires the owner's fresh direct reply to that exact preview; this never approves execution.",
                 "parameters": {"type": "object", "properties": {
                     "title": {"type": "string", "minLength": 5, "maxLength": 120,
                               "description": "Single-line task title."},
                     "task_type": {"type": "string", "enum": ["feature", "bugfix", "test", "docs", "refactor"]},
                     **{field: {"type": "string", "minLength": 1, "maxLength": 20000}
                        for field in FIELDS if field not in {"title", "task_type", "acceptance_criteria"}},
                     "acceptance_criteria": {"type": "string", "minLength": 1, "maxLength": 20000,
                                             "description": "Include at least one '- [ ] ...' checkbox."}},
                     "required": list(FIELDS), "additionalProperties": False}}
STATUS_SCHEMA = {"name": "development_gateway_status",
                 "description": "After an owner direct reply to the development preview, check the trusted Gateway filing outcome for this Photon turn and report the canonical task ID only if filed.",
                 "parameters": {"type": "object", "properties": {},
                                "additionalProperties": False}}


def register(ctx):
    ctx.register_tool(name="development_gateway_submit", toolset="alfred_development_gateway_intake",
                      schema=SUBMIT_SCHEMA, handler=development_gateway_submit,
                      description=SUBMIT_SCHEMA["description"])
    ctx.register_tool(name="development_gateway_status", toolset="alfred_development_gateway_intake",
                      schema=STATUS_SCHEMA, handler=development_gateway_status,
                      description=STATUS_SCHEMA["description"])
