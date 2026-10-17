from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


HERE = Path(__file__).resolve().parents[1]
AUTHORITATIVE = Path("/home/alfred/Git/alfred")


def test_conditional_record_is_explicitly_non_authorizing():
    record = json.loads((HERE / "APPROVAL_RECORD_CANDIDATE.json").read_text())
    assert record["formal_adr_recording"] == "pending_human_action"
    assert record["task_a_canonical_id"] is None and record["task_a_ready"] is False
    assert record["protected_path_approval"] is False
    assert record["production_migration_approval"] is False
    assert record["task_b_start_allowed"] is False
    adr = AUTHORITATIVE / "docs/adr/0003-development-gateway.md"
    proposal = HERE.parent / "proposals/ADR-0003-photon-gateway-front-amendment.md"
    assert hashlib.sha256(adr.read_bytes()).hexdigest() == record["authoritative_adr_sha256"]
    assert hashlib.sha256(proposal.read_bytes()).hexdigest() == record["staging_amendment_sha256"]


def test_exact_proposed_patch_applies_without_modifying_authoritative_repo():
    patch = HERE / "adr-0003-conditional-photon-front.proposed.patch"
    result = subprocess.run(["git", "apply", "--check", str(patch)], cwd=AUTHORITATIVE, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
