"""Exercise real Gateway filing and CTO planning in disposable directories only."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
GATEWAY = Path("/home/alfred/Git/alfred")
sys.path.insert(0, str(GATEWAY / "src"))
sys.path.insert(0, str(GATEWAY / ".dev" / "bin"))
sys.path.insert(0, str(ROOT.parent))

from alfred.gateway.dispatcher import GatewayConfig, run_once  # noqa: E402
from alfred.registry.loader import parse_registry  # noqa: E402
from cto import poll, show_plan  # noqa: E402
from developer_v1.gateway_adapter import read_gateway_inputs  # noqa: E402
from developer_v1.router import select_specialists  # noqa: E402
from intake import IntakeFiler  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="alfred-dev-v1-gateway-dryrun-") as temporary:
        root = Path(temporary)
        repo = root / "repo"
        shutil.copytree(ROOT / "repo", repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        data = yaml.safe_load((ROOT / "projects.proposed.yaml").read_text())
        project = next(p for p in data["projects"] if p["id"] == "dev-v1-accept")
        project["local_path"] = str(repo)
        registry_file = root / "projects.yaml"
        registry_file.write_text(yaml.safe_dump(data, sort_keys=False))
        registry = parse_registry(data)
        intake = root / "intake"
        (intake / "inbox").mkdir(parents=True)
        (intake / "inbox" / "acceptance-fixture.json").write_bytes(
            (ROOT / "gateway-envelope.fixture.json").read_bytes())
        gateway_state = root / "gateway"
        gateway_state.mkdir()
        report = run_once(registry, IntakeFiler(), GatewayConfig(
            intake_dir=intake, gateway_dir=gateway_state, home=Path.home(),
            today="2026-10-15", requester="hermes"))
        assert report.filed == ["T-0002"] and not report.rejected and not report.clarifications
        uncertain_state = root / "uncertain-gateway"
        (uncertain_state / "cto-plans").mkdir(parents=True)
        shutil.copy2(gateway_state / "journal.jsonl", uncertain_state / "journal.jsonl")
        delivery = root / "delivery.json"
        delivery.write_text("{}")

        def uncertain_send(unused, message):
            raise TimeoutError("synthetic delivery acknowledgment lost")

        def unexpected_send(unused, message):
            raise AssertionError("CTO attempted duplicate delivery")

        uncertain = poll(gateway_dir=uncertain_state, registry_path=registry_file,
                         config_path=delivery, sender=uncertain_send)
        assert uncertain["planned"] == 1 and uncertain["delivered"] == 0
        uncertain_plan = show_plan(uncertain_state, "dev-v1-accept", "T-0002")
        assert uncertain_plan["delivery"]["state"] == "attempted_uncertain"
        uncertain_repeat = poll(gateway_dir=uncertain_state, registry_path=registry_file,
                                config_path=delivery, sender=unexpected_send)
        assert uncertain_repeat["existing"] == 1 and uncertain_repeat["delivered"] == 0

        counts = poll(gateway_dir=gateway_state, registry_path=registry_file,
                      config_path=delivery, sender=lambda unused, message: "fixture-plan-message")
        assert counts["planned"] == 1 and counts["delivered"] == 1
        plan = show_plan(gateway_state, "dev-v1-accept", "T-0002")
        inputs = read_gateway_inputs(gateway_root=GATEWAY, gateway_state=gateway_state,
                                     registry_path=registry_file,
                                     project_id="dev-v1-accept", task_id="T-0002")
        roles = select_specialists(inputs.spec_decoder(inputs.spec_raw), plan)
        assert roles == ["backend"] and plan["clarification_required"] is False
        (intake / "inbox" / "acceptance-fixture-again.json").write_bytes(
            (ROOT / "gateway-envelope.fixture.json").read_bytes())
        duplicate = run_once(registry, IntakeFiler(), GatewayConfig(
            intake_dir=intake, gateway_dir=gateway_state, home=Path.home(),
            today="2026-10-15", requester="hermes"))
        assert duplicate.duplicates == ["acceptance-fixture-again.json"]
        assert not duplicate.filed

        repeat = poll(gateway_dir=gateway_state, registry_path=registry_file,
                      config_path=delivery, sender=unexpected_send)
        assert repeat["existing"] == 1 and repeat["delivered"] == 0
        print(json.dumps({"state": "passed_disposable_gateway_fixture",
                          "filed": report.filed, "planned": counts["planned"],
                          "clarification_required": plan["clarification_required"],
                          "specialists": roles, "duplicate_filing_denied": True,
                          "duplicate_cto_send_denied": True,
                          "uncertain_cto_send_not_retried": True}, sort_keys=True))


if __name__ == "__main__":
    main()
