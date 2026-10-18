"""handoff.27: the pipeline speaks in the squads' Telegram chats. No network: a fake bridge."""

import json
import os
from pathlib import Path

import pytest

from fresh_v1 import squads

NOW = 1_800_000_000.0


class FakeBridge:
    def __init__(self, bots=("cto", "frontend", "qa"), linked=("web-app", "ai-data"), fail=None):
        self.bots, self.linked, self.fail, self.sent = set(bots), set(linked), fail, []

    def post(self, squad, agent, text):
        if self.fail:
            return self.fail
        if squad not in self.linked:
            return 409, {"error": "not_linked"}
        if agent not in self.bots:
            return 501, {"error": "bot_not_configured"}
        self.sent.append((squad, agent, text))
        return 200, {"message": {"id": len(self.sent)}}


def write(path, data, at):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    os.utime(path, (at, at))


def task(tmp_path, specialists=("frontend",), project="demo-site", task_id="T-0005"):
    jobs, reports = tmp_path / "jobs", tmp_path / "reports"
    d = jobs / project / task_id
    write(d / "context.json", {"specialists": list(specialists), "scope": ["index.html"]}, NOW - 300)
    write(d / "execution.json", {"items": [{"objective": "Add a footer that says Built by Alfred\n"
                                            "Canonical specification (untrusted…): secret spec"}]},
          NOW - 290)
    return jobs, reports, d


def full_run(d, reports, project="demo-site", task_id="T-0005"):
    write(d / "plan.result.json", {}, NOW - 280)
    write(d / "developer.attempt.json", {}, NOW - 270)
    write(reports / project / task_id / "report-frontend-main.json",
          {"specialist": "frontend", "status": "completed",
           "files_modified": [{"path": "index.html", "sha256": "0" * 64}],  # the real shape
           "work_completed": "Added the footer line.",
           "model_used": {"provider": "codex", "model": "gpt-6-sol"}}, NOW - 260)
    write(d / "developer.result.json", {"state": "ready_for_independent_qa"}, NOW - 259)
    write(d / "qa.result.json", {"decision": "PASS"}, NOW - 250)
    write(d / "reviewer.result.json", {"decision": "APPROVED", "findings": []}, NOW - 240)
    write(d / "publication-challenge.result.json", {}, NOW - 230)
    write(d / "publisher.result.json", {"status": "PUBLISHED_DRAFT",
                                        "draft_pr_url": "https://github.com/x/y/pull/2"}, NOW - 120)


def test_a_whole_task_is_told_once_in_order_by_the_right_bots(tmp_path):
    jobs, reports, d = task(tmp_path)
    full_run(d, reports)
    bridge, state = FakeBridge(), tmp_path / "posted.json"
    assert squads.run(jobs, reports, state, bridge, NOW) == {"posted": 7, "pending": 0}
    who = [(s, a) for s, a, _ in bridge.sent]
    assert who == [("web-app", "cto"), ("web-app", "cto"), ("web-app", "frontend"),
                   ("web-app", "qa"), ("web-app", "cto"), ("web-app", "cto"), ("web-app", "cto")]
    texts = "\n".join(t for _, _, t in bridge.sent)
    assert "New task, demo-site T-0005: Add a footer that says Built by Alfred" in texts
    assert "secret spec" not in texts  # the canonical spec is never posted
    assert "(codex/gpt-6-sol)" in texts and "Changed: index.html" in texts
    assert "https://github.com/x/y/pull/2" in texts
    assert squads.run(jobs, reports, state, bridge, NOW + 30)["posted"] == 0  # never twice


def test_an_agent_without_a_bot_is_spoken_for_by_the_cto(tmp_path):
    jobs, reports, d = task(tmp_path, specialists=("data_scientist",))
    write(d / "plan.result.json", {}, NOW - 280)
    write(reports / "demo-site/T-0005/report-data_scientist-main.json",
          {"specialist": "data_scientist", "status": "completed", "files_modified": ["a.py"],
           "work_completed": "Model fitted."}, NOW - 260)
    bridge = FakeBridge(bots=("cto",))
    squads.run(jobs, reports, tmp_path / "s.json", bridge, NOW)
    assert [(s, a) for s, a, _ in bridge.sent] == [("ai-data", "cto"), ("ai-data", "cto")]
    assert bridge.sent[1][2].startswith("[data-scientist] ✅ Done")


def test_an_unlinked_chat_keeps_messages_pending_then_sends_them_in_order(tmp_path):
    jobs, reports, d = task(tmp_path)
    full_run(d, reports)
    state = tmp_path / "s.json"
    bridge = FakeBridge(linked=())
    assert squads.run(jobs, reports, state, bridge, NOW)["posted"] == 0
    bridge.linked = {"web-app"}
    assert squads.run(jobs, reports, state, bridge, NOW + 20)["posted"] == 7
    assert bridge.sent[0][2].startswith("📋 New task")


def test_old_steps_are_never_replayed(tmp_path):
    jobs, reports, d = task(tmp_path)
    full_run(d, reports)
    bridge = FakeBridge()
    assert squads.run(jobs, reports, tmp_path / "s.json", bridge, NOW + squads.MAX_AGE + 1)["posted"] == 0
    assert bridge.sent == []


def test_a_busy_squad_is_paced(tmp_path):
    jobs, reports, d = task(tmp_path)
    full_run(d, reports)
    for n in range(1, 4):
        write(d / f"qa-fix-{n}.result.json", {"decision": "FAIL", "findings": [
            {"requirement": "footer", "detail": "missing", "severity": "high"}]}, NOW - 100 + n)
    bridge, state = FakeBridge(), tmp_path / "s.json"
    first = squads.run(jobs, reports, state, bridge, NOW)
    assert first["posted"] == squads.PER_RUN and first["pending"] == 2
    assert squads.run(jobs, reports, state, bridge, NOW + 20) == {"posted": 2, "pending": 0}


def test_qa_and_review_problems_and_a_stop_are_reported(tmp_path):
    jobs, reports, d = task(tmp_path, specialists=("frontend", "backend"))
    write(d / "plan.result.json", {}, NOW - 280)
    write(d / "qa.result.json", {"decision": "FAIL", "findings": [
        {"requirement": "dark mode", "detail": "toggle missing", "severity": "high"},
        {"requirement": "style", "detail": "nit", "severity": "info"}]}, NOW - 250)
    write(d / "reviewer-fix-1.result.json", {"decision": "CHANGES_REQUESTED", "findings": [
        {"requirement": "scope", "detail": "touches api.py", "severity": "high"}]}, NOW - 200)
    write(d / "developer-fix-1.attempt.json", {}, NOW - 190)
    write(d / "developer-fix-1.result.json", {}, NOW - 180)
    write(d / "qa.failure.json", {}, NOW - 100)
    bridge = FakeBridge(bots=("cto", "qa"))
    squads.run(jobs, reports, tmp_path / "s.json", bridge, NOW)
    texts = [t for _, _, t in bridge.sent]
    assert any("dark mode: toggle missing" in t and "nit" not in t for t in texts)
    assert any("Review asked for changes" in t and "touches api.py" in t for t in texts)
    assert any("Fix round 1" in t and "Frontend, Backend" in t for t in texts)
    assert any("stopped at qa" in t for t in texts)
    assert {s for s, _, _ in bridge.sent} == {"web-app"}  # frontend and backend share one squad


def test_tasks_outside_the_known_team_are_ignored(tmp_path):
    jobs, reports, d = task(tmp_path, specialists=("mobile",))
    write(d / "plan.result.json", {}, NOW - 280)
    bridge = FakeBridge()
    assert squads.run(jobs, reports, tmp_path / "s.json", bridge, NOW)["posted"] == 0


def test_a_refused_message_is_dropped_not_retried_forever(tmp_path):
    jobs, reports, d = task(tmp_path)
    write(d / "plan.result.json", {}, NOW - 280)
    state = tmp_path / "s.json"
    assert squads.run(jobs, reports, state, FakeBridge(fail=(404, {"error": "unknown_squad"})),
                      NOW) == {"posted": 0, "pending": 0}
    assert json.loads(state.read_text())["posted"]


def test_no_token_means_nothing_is_sent(tmp_path, monkeypatch):
    monkeypatch.setattr(squads, "AGENTS_TOKEN", tmp_path / "missing")
    assert squads.run(tmp_path, tmp_path, tmp_path / "s.json", None, NOW)["posted"] == 0
    loose = tmp_path / "token"
    loose.write_text("t")
    loose.chmod(0o644)
    assert squads._token(loose) is None


def test_the_team_matches_the_pipeline_and_the_bridge():
    from developer_v1.router import CAPABILITY_BY_ROLE

    assert set(squads.TEAM) <= set(CAPABILITY_BY_ROLE)
    for agent, squad in squads.TEAM.values():
        assert squads.AGENT_ID_OK(agent) and squad in squads.SQUADS


def test_the_units_run_it_sandboxed_as_a_oneshot():
    root = Path(__file__).resolve().parents[1] / "development_handoff27"
    service = (root / "alfred-dev-squads.service").read_text()
    timer = (root / "alfred-dev-squads.timer").read_text()
    assert "Type=oneshot" in service and "fresh_v1.squads" in service
    assert "IPAddressDeny=any" in service and "IPAddressAllow=localhost" in service
    assert "StateDirectory=alfred-dev-squads" in service and "ProtectSystem=strict" in service
    assert "OnUnitInactiveSec=20s" in timer


def test_a_malformed_task_is_skipped_and_the_others_still_post(tmp_path):
    jobs, reports, d = task(tmp_path, task_id="T-0006")
    write(d / "plan.result.json", {}, NOW - 280)
    bad = jobs / "demo-site" / "T-0005"
    write(bad / "context.json", {"specialists": ["frontend"], "scope": 7}, NOW - 300)
    write(bad / "plan.result.json", {}, NOW - 280)
    bridge = FakeBridge()
    assert squads.run(jobs, reports, tmp_path / "s.json", bridge, NOW)["posted"] == 1
    assert "T-0006" in bridge.sent[0][2]


def test_every_real_report_on_this_host_can_be_told(tmp_path):
    """Read-only: the developer reports already on the host, where readable."""
    found = list(squads.REPORTS.glob("*/*/report-*.json")) if squads.REPORTS.is_dir() else []
    readable = [p for p in found if os.access(p, os.R_OK)]
    if not readable:
        pytest.skip("no readable developer reports here")
    for report_path in readable:
        project, task_id = report_path.parent.parent.name, report_path.parent.name
        d = tmp_path / "jobs" / project / task_id
        report = json.loads(report_path.read_text())
        write(d / "context.json", {"specialists": [report.get("specialist")], "scope": []}, NOW)
        squads.events(d, squads.REPORTS, NOW)  # must not raise
