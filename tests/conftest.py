from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


TASK_A = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TASK_A))
sys.path.insert(0, "/home/alfred/Git/alfred/src")
sys.path.insert(0, "/home/alfred/Git/alfred/.dev/bin")


@pytest.fixture
def lab_root(tmp_path: Path) -> Path:
    (tmp_path / ".task-a-isolated-root").write_text("TASK_A_LAB_ONLY\n")
    return tmp_path


@pytest.fixture
def envelope_data() -> dict:
    return {
        "protocol": "alfred.devreq/1",
        "request_id": "3f2b8c1e-4a5d-4e6f-9a7b-1c2d3e4f5a6b",
        "revision": 1,
        "submitted_at": "2026-10-14T09:30:00Z",
        "origin": {"interface": "photon", "conversation_ref": "lab-space/lab-message"},
        "utterance": "Please create a laboratory documentation task.",
        "project_hint": "dev-001",
        "intent_confidence": 1.0,
        "draft": {
            "title": "Document the lab transport",
            "task_type": "docs",
            "objective": "Document the disposable lab transport.",
            "scope": "In: laboratory documentation.\nOut: live service changes.",
            "requirements": "Record the isolated request path.",
            "constraints": "No live Gateway operation.",
            "acceptance_criteria": "- [ ] The lab documentation is complete.",
            "security_considerations": "No credential or protected state access.",
            "testing_requirements": "Review the isolated fixture.",
        },
        "answers": [],
    }


@pytest.fixture
def envelope_bytes(envelope_data: dict) -> bytes:
    return json.dumps(envelope_data, sort_keys=True, separators=(",", ":")).encode()
