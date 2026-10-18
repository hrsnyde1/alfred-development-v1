"""handoff.21 (Phase 1): the development agents run on Claude with their own identity.

No real model is called: a fake `claude` executable answers `-p` and records the
arguments and environment it was given. handoff.26: the agents use their own token and
a private home, never the owner's own Claude Code login."""

import json
import os
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from developer_v1 import agent_profiles, pipeline
from developer_v1.real_worker import (CLAUDE_EFFORT, ClaudeReadOnlyBroker, CodexReadOnlyBroker,
                                      DeveloperWorker, RoutingBroker)
from developer_v1.router import (CAPABILITY_BY_ROLE, EFFORTS, Denied, ModelChoice,
                                 ProviderUnavailable, select_model)

ROOT = Path(__file__).resolve().parents[1]
EDITS = {"edits": [{"path": "app.js", "content": "// dark mode\n"}], "summary": "Dark mode."}
SONNET = ModelChoice("claude", "claude-sonnet-5-5", "medium", ("read_scoped",), False)
CODEX = ModelChoice("codex", "gpt-6-sol", "high", ("read_scoped",), True)
DEVELOPER_TOOLS = ("read_scoped", "write_scoped", "run_approved_check",
                   "git_local_commit_if_granted")


TOKEN = "sk-ant-oat01-" + "x" * 40


def fake_claude(tmp_path, answer, *, exit_code=0, stderr=""):
    log = tmp_path / "argv.json"
    cli = tmp_path / "claude"
    cli.write_text(
        "#!/usr/bin/python3\nimport json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'cwd': os.getcwd(), 'env': dict(os.environ)}},"
        f" open({str(log)!r}, 'w'))\n"
        f"sys.stdout.write({json.dumps(answer)!r})\nsys.stderr.write({stderr!r})\n"
        f"sys.exit({exit_code})\n")
    cli.chmod(0o755)
    return cli, log


def result(contract=EDITS, **extra):
    return {"type": "result", "subtype": "success", "is_error": False,
            "structured_output": contract, **extra}


def generate(tmp_path, answer, choice=SONNET, token=TOKEN, **kwargs):
    cli, log = fake_claude(tmp_path, answer, **kwargs)
    broker = ClaudeReadOnlyBroker(executable=str(cli), home=tmp_path / "agents")
    with patch("developer_v1.real_worker._claude_token", return_value=token):
        contract = broker.generate(choice, objective="Add dark mode.", sources={"app.js": ""},
                                   identity="You are the Frontend Engineer.")
    return contract, json.loads(log.read_text())


# --- The Claude route -----------------------------------------------------------------------

def test_claude_returns_the_edit_contract_with_no_tools(tmp_path):
    contract, call = generate(tmp_path, result())
    argv = call["argv"]
    assert contract == EDITS
    option = lambda name: argv[argv.index(name) + 1]  # noqa: E731
    assert option("--tools") == "" and option("--model") == "claude-sonnet-5-5"
    assert option("--effort") == "medium" and option("--output-format") == "json"
    assert option("--setting-sources") == "project"
    assert {"--strict-mcp-config", "--no-session-persistence",
            "--disable-slash-commands"} <= set(argv)
    assert json.loads(option("--json-schema"))["required"]
    assert "You are the Frontend Engineer." in option("--append-system-prompt")
    assert "never permits other files" in option("--append-system-prompt")
    assert json.loads(option("-p"))["files"] == {"app.js": ""}
    assert not os.listdir(call["cwd"]) if os.path.exists(call["cwd"]) else True


def test_claude_runs_with_the_agents_token_in_a_private_home(tmp_path):
    _, call = generate(tmp_path, result())
    env = call["env"]
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == TOKEN
    assert env["HOME"] == str(tmp_path / "agents")
    assert oct((tmp_path / "agents").stat().st_mode & 0o777) == "0o700"
    assert set(env) <= {"HOME", "PATH", "CLAUDE_CODE_OAUTH_TOKEN", "DISABLE_AUTOUPDATER",
                        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "PWD", "LC_CTYPE", "_"}


def test_the_token_file_must_be_root_owned_and_private(tmp_path):
    from developer_v1.real_worker import _claude_token

    path = tmp_path / "token"
    path.write_text(TOKEN + "\n")
    path.chmod(0o640)
    # Owned by the test user, not root: refused, so Claude counts as unavailable.
    assert _claude_token(path) is None
    assert _claude_token(tmp_path / "missing") is None
    with patch("developer_v1.real_worker.os.fstat",
               return_value=os.stat_result((0o100640, 0, 0, 1, 0, 0, len(TOKEN) + 1, 0, 0, 0))):
        assert _claude_token(path) == TOKEN
    with patch("developer_v1.real_worker.os.fstat",
               return_value=os.stat_result((0o100644, 0, 0, 1, 0, 0, len(TOKEN) + 1, 0, 0, 0))):
        assert _claude_token(path) is None  # world-readable


def test_the_sandbox_no_longer_opens_the_owners_claude_login():
    conf = (ROOT / "development_handoff26/60-claude-agents.conf").read_text()
    assert [l for l in conf.splitlines() if l and not l.startswith("#")] == ["[Service]"]


def test_every_catalog_effort_maps_to_one_claude_accepts():
    assert set(CLAUDE_EFFORT) == EFFORTS
    assert set(CLAUDE_EFFORT.values()) <= {"low", "medium", "high", "xhigh", "max"}


@pytest.mark.parametrize("answer,kwargs", [
    (result(), {"token": None}),
    ({"type": "result", "is_error": True, "result": "API Error: rate limit"}, {"exit_code": 1}),
    # T-0004: a token refresh that could not take its lock.
    ({"type": "result", "subtype": "success", "is_error": True, "terminal_reason": "api_error",
      "result": "Failed to refresh OAuth token: another Claude Code process is refreshing it"},
     {"exit_code": 1}),
    ({"type": "result", "subtype": "success", "is_error": True, "terminal_reason": "api_error",
      "result": "Failed to authenticate. API Error: 401 OAuth access token is invalid."},
     {"exit_code": 1}),
    ("", {"exit_code": 1, "stderr": "Error: usage limit reached"}),
])
def test_an_unavailable_claude_route_allows_the_approved_fallback(tmp_path, answer, kwargs):
    with pytest.raises(ProviderUnavailable):
        generate(tmp_path, answer, **kwargs)


@pytest.mark.parametrize("answer", [
    result({"edits": [], "summary": "x", "extra": 1}),
    result({"edits": "app.js"}),
    {**result(), "subtype": "error_max_turns"},
    "not json",
])
def test_a_malformed_claude_answer_is_refused(tmp_path, answer):
    with pytest.raises(Denied):
        generate(tmp_path, answer, exit_code=0)


def test_claude_refuses_a_codex_route(tmp_path):
    with pytest.raises(ProviderUnavailable):
        generate(tmp_path, result(), choice=CODEX)


# --- Routing between providers --------------------------------------------------------------

class Recording:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def authenticated(self):
        return not self.fail

    def generate(self, choice, **kwargs):
        self.calls.append((choice.provider, kwargs))
        if self.fail:
            raise ProviderUnavailable("down")
        return EDITS


def test_each_choice_goes_to_its_own_provider():
    claude, codex = Recording(), Recording()
    broker = RoutingBroker({"claude": claude, "codex": codex})
    broker.generate(SONNET, objective="o", sources={}, identity="me")
    broker.generate(CODEX, objective="o", sources={})
    assert claude.calls == [("claude", {"objective": "o", "sources": {}, "identity": "me"})]
    assert codex.calls == [("codex", {"objective": "o", "sources": {}})]
    with pytest.raises(ProviderUnavailable):
        broker.generate(ModelChoice("other", "m", "low", (), False), objective="o", sources={})


def test_claude_outage_falls_back_to_the_approved_codex_model(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "app.js").write_text("")
    for args in (["add", "app.js"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base"]):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True)
    claude, codex = Recording(fail=True), Recording()
    worker = DeveloperWorker(RoutingBroker({"claude": claude, "codex": codex}), objective="o",
                             checks=[], fallback=replace(CODEX, tools=DEVELOPER_TOOLS),
                             identity="You are the Frontend Engineer.")
    try:
        worker.execute({"files": ["app.js"]}, tmp_path, replace(SONNET, tools=DEVELOPER_TOOLS))
    except Denied:
        pass  # later steps need the real sandbox; the route decision is what matters here
    assert [c[0] for c in claude.calls + codex.calls] == ["claude", "codex"]
    assert codex.calls[0][1]["identity"] == "You are the Frontend Engineer."
    assert worker.actual_model == {"provider": "codex", "model": "gpt-6-sol"}


def test_codex_receives_the_profile_as_part_of_its_payload():
    broker = CodexReadOnlyBroker(executable="/bin/true")
    answer = json.dumps(EDITS)
    stdout = "\n".join(json.dumps(e) for e in (
        {"type": "item.completed", "item": {"type": "agent_message", "text": answer}},
        {"type": "turn.completed"}))
    prompts = []

    def run(command, **kwargs):
        prompts.append(json.loads(command[-1]))
        return subprocess.CompletedProcess(command, 0, stdout, "")

    with patch.object(broker, "authenticated", return_value=True), \
            patch("developer_v1.real_worker.subprocess.run", side_effect=run):
        broker.generate(CODEX, objective="o", sources={"a.py": ""})
        broker.generate(CODEX, objective="o", sources={"a.py": ""}, identity="You are QA.")
    assert "agent_profile" not in prompts[0]
    assert prompts[1]["agent_profile"] == "You are QA."


def test_a_profile_counts_toward_the_prompt_budget():
    with pytest.raises(Denied):
        DeveloperWorker(Recording(), objective="o", checks=[], identity="x" * 30000)


# --- Agent profiles -------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def protected_bundle(tmp_path_factory, monkeypatch):
    """The installed bundle is root-owned 0644; a checkout may be group-writable."""
    copy = tmp_path_factory.mktemp("release") / "agent_profiles.json"
    copy.write_bytes(agent_profiles.BUNDLE.read_bytes())
    copy.chmod(0o644)
    monkeypatch.setattr(agent_profiles, "BUNDLE", copy)


AGENTS = {"cto", "frontend", "backend", "full_stack", "data_scientist", "data_engineer",
          "ai_ml", "devops", "integration", "builder", "qa", "security", "reviewer"}


def test_the_release_carries_all_thirteen_reviewed_profiles():
    bundle = json.loads(agent_profiles.BUNDLE.read_text())
    assert set(bundle["agents"]) == AGENTS
    assert bundle["source"]["repository"] == "hrsnyde1/alfred-team-skills"
    assert set(bundle["squads"]) == {"core", "web", "ai", "infra", "security"}
    for agent in AGENTS:
        text = agent_profiles.identity(agent)
        assert text.startswith("# ") and len(text.encode()) <= agent_profiles.MAX_PROFILE
        assert agent_profiles.card(agent)["id"] == agent


def test_specialists_without_a_profile_get_none():
    assert agent_profiles.identity("mobile") == ""
    assert agent_profiles.card("mobile") is None


def test_an_unprotected_bundle_is_refused(tmp_path):
    copy = tmp_path / "agent_profiles.json"
    copy.write_bytes(agent_profiles.BUNDLE.read_bytes())
    copy.chmod(0o664)
    with pytest.raises(Denied):
        agent_profiles.identity("frontend", copy)
    assert agent_profiles.identity("frontend", tmp_path / "missing.json") == ""


def test_the_bundle_matches_its_source_files(tmp_path):
    agents = tmp_path / "agents"
    bundle = json.loads(agent_profiles.BUNDLE.read_text())
    for agent, profile in bundle["agents"].items():
        (agents / agent).mkdir(parents=True)
        (agents / agent / "agent.json").write_text(json.dumps(profile["card"]))
        for name, part in zip(agent_profiles.FILES, profile["text"].split("\n\n# ")):
            (agents / agent / name).write_text(part if part.startswith("# ") else "# " + part)
    (agents / "squads.json").write_text(json.dumps({"squads": bundle["squads"]}))
    assert agent_profiles.build(agents, bundle["source"]["commit"]) == bundle


# --- The per-role model catalog -------------------------------------------------------------

MODELS = json.loads((ROOT / "development_handoff21/models.json").read_text())


def available(config):
    return {(p, m) for p, catalog in config["providers"].items() for m in catalog}


@pytest.mark.parametrize("role", sorted(MODELS["specialists"]))
def test_each_role_runs_on_its_profile_model_with_a_codex_fallback(role):
    choice = select_model(MODELS, role, available=available(MODELS),
                          required_capabilities=CAPABILITY_BY_ROLE[role], max_cost=6,
                          complexity="high")
    card = agent_profiles.card(role)
    if card and card["provider"] == "claude":
        assert (choice.provider, choice.model) == ("claude", card["model"])
        assert choice.reasoning_effort == card["effort"]
        fallback = select_model(MODELS, role,
                                available=available(MODELS) - {(choice.provider, choice.model)},
                                required_capabilities=CAPABILITY_BY_ROLE[role], max_cost=6,
                                complexity="high")
        assert fallback.provider == "codex" and fallback.fallback_used
    else:
        assert choice.provider == "codex"
    assert set(choice.tools) == set(DEVELOPER_TOOLS)


def test_the_new_catalog_keeps_every_existing_codex_model():
    live_shape = json.loads((ROOT / "developer_v1/models.codex-verified.example.json").read_text())
    # handoff.21's catalog predates builder, qa and code_reviewer; their slots come
    # from the Alfred OS applier, and V1 fails closed before the grant without them.
    assert set(live_shape["specialists"]) - set(MODELS["specialists"]) == {
        "builder", "qa", "code_reviewer"}
    assert set(MODELS["providers"]) == {"claude", "codex"}


def test_the_pipeline_accepts_claude_and_codex_but_nothing_else():
    assert pipeline.PROVIDERS == {"claude", "codex"}
    source = (ROOT / "developer_v1/pipeline.py").read_text()
    assert 'providers[first.provider][first.model]["max_task_cost"]' in source
    # Profiles are read before the grant is claimed, so a bad bundle leaves it unused.
    assert source.index("agent_profiles.identity(") < source.index("authority.claim(")
    # So are the owner-approved Alfred OS snapshots (team_snapshot.py).
    assert source.index("team_snapshot.profile(") < source.index("authority.claim(")
