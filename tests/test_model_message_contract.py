"""handoff.6: Codex may send progress notes before its schema-bound final message
(T-0007: {"status": ...} then the edits). Developer and Reviewer accept exactly one
contract-shaped message, which must be the final one. No real model is called."""

import json
import os
from pathlib import Path

import pytest

from developer_v1.real_worker import CodexReadOnlyBroker
from developer_v1.router import Denied, ModelChoice
from independent_reviewer import worker as reviewer
from independent_reviewer.worker import EvidenceError

EDITS = {"edits": [{"path": "calculator.py", "content": "def negate(a):\n    return -a\n"}],
         "summary": "Add negate."}
DECISION = {"decision": "APPROVED", "findings": [],
            "coverage": [{"criterion": "negate(a) returns -a", "result": "PASS",
                          "evidence": "test_negate"}]}
STATUS = {"status": "Implementing the requested helper."}


def fake_codex(tmp_path, messages):
    """An executable that answers `login status` and emits one Codex JSON stream."""
    events = [{"type": "thread.started"}, {"type": "turn.started"}]
    events += [{"type": "item.completed", "item": {"type": "agent_message", "text": text}}
               for text in messages]
    events.append({"type": "turn.completed"})
    stream = tmp_path / "events.jsonl"
    stream.write_text("".join(json.dumps(e) + "\n" for e in events))
    cli = tmp_path / "codex"
    cli.write_text(
        "#!/usr/bin/python3\nimport sys\n"
        "if sys.argv[1:3] == ['login', 'status']:\n    print('Logged in using ChatGPT')\n"
        f"else:\n    sys.stdout.write(open({str(stream)!r}).read())\n")
    cli.chmod(0o755)
    return cli


def develop(tmp_path, messages):
    broker = CodexReadOnlyBroker(executable=str(fake_codex(tmp_path, messages)))
    choice = ModelChoice("codex", "gpt-6-sol", "high", ("read_scoped",), False)
    return broker.generate(choice, objective="Add negate(a).",
                           sources={"calculator.py": "def add(a, b):\n    return a + b\n"})


def review(tmp_path, messages):
    context = {
        "model": {"provider": "codex", "model": "gpt-6-astra", "reasoning_effort": "high",
                  "cli": str(fake_codex(tmp_path, messages)), "timeout_seconds": 30},
        "plan": {"objective": "Add negate.", "scope": ["calculator.py"],
                 "acceptance_criteria": "- [ ] negate(a) returns -a"},
        "report": {"acceptance_criteria": [], "tests": []},
        "diff": "diff --git a/calculator.py b/calculator.py\n",
    }
    return reviewer.review_with_model(context)


@pytest.mark.parametrize("messages", [
    [json.dumps(EDITS)],
    [json.dumps(STATUS), json.dumps(EDITS)],  # The observed T-0007 shape.
    ["Working on it.", json.dumps(STATUS), json.dumps(EDITS)],
])
def test_developer_accepts_one_final_edit_contract(tmp_path, messages):
    assert develop(tmp_path, messages) == EDITS


@pytest.mark.parametrize("messages,reason", [
    ([], "ambiguous"),
    ([json.dumps(EDITS), json.dumps(EDITS)], "ambiguous"),
    ([json.dumps(EDITS), json.dumps(STATUS)], "contract invalid"),  # Not final.
    ([json.dumps(STATUS)], "contract invalid"),
    (["not json"], "not JSON"),
    ([json.dumps({**EDITS, "extra": 1})], "contract invalid"),
    ([json.dumps({"edits": "calculator.py", "summary": "x"})], "contract invalid"),
])
def test_developer_still_refuses_ambiguous_or_invalid_answers(tmp_path, messages, reason):
    with pytest.raises(Denied, match=reason):
        develop(tmp_path, messages)


@pytest.mark.parametrize("messages", [
    [json.dumps(DECISION)],
    [json.dumps(STATUS), json.dumps(DECISION)],
])
def test_reviewer_accepts_one_final_decision(tmp_path, messages):
    answer, used = review(tmp_path, messages)
    assert answer == DECISION and used["model"] == "gpt-6-astra"


@pytest.mark.parametrize("messages", [
    [],
    [json.dumps(DECISION), json.dumps(DECISION)],
    [json.dumps(DECISION), json.dumps(STATUS)],
    [json.dumps(STATUS)],
])
def test_reviewer_still_refuses_missing_duplicate_or_non_final_decisions(tmp_path, messages):
    with pytest.raises(EvidenceError):
        review(tmp_path, messages)


def test_fake_cli_is_executable_only_in_tmp(tmp_path):
    cli = fake_codex(tmp_path, [])
    assert cli.is_relative_to(tmp_path) and os.access(cli, os.X_OK)
    assert Path("/usr/bin/python3").is_file()
