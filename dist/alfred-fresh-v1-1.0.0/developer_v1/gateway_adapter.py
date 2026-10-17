"""Read-only bridge to the existing Gateway registry, task parser and CTO schema.

Requires the Gateway repository's own Python environment. This module never
transitions approval state or writes Gateway artifacts.
"""

from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from .router import Denied


def _regular(path: Path, maximum: int) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise Denied("Gateway artifact is not a bounded regular file")
        raw = os.read(fd, maximum + 1)
        if len(raw) > maximum:
            raise Denied("Gateway artifact is too large")
        return raw
    finally:
        os.close(fd)


@dataclass(frozen=True)
class GatewayInputs:
    repository: Path
    spec_raw: bytes
    plan_raw: bytes
    spec_decoder: object


def read_gateway_inputs(
    *,
    gateway_root: Path,
    gateway_state: Path,
    project_id: str,
    task_id: str,
    registry_path: Path,
) -> GatewayInputs:
    """Resolve a canonical task through the protected registry, then validate both files."""
    if not gateway_root.is_absolute() or not gateway_state.is_absolute():
        raise Denied("Gateway paths must be absolute")
    sys.path.insert(0, str(gateway_root / "src"))
    sys.path.insert(0, str(gateway_root / ".dev" / "bin"))
    try:
        import json

        from alfred.gateway.journal import Journal
        from alfred.registry.loader import parse_registry, read_registry_data
        from jsonschema import Draft202012Validator
        from taskspec import parse, validate

        registry = parse_registry(read_registry_data(registry_path))
        project = registry.project(project_id)
        if (
            project is None
            or project.status != "active"
            or not project.permissions.hermes_requests
        ):
            raise Denied("project not available to Hermes Gateway")
        repository = project.resolved_path(Path.home())
        if repository.is_symlink() or not repository.is_dir():
            raise Denied("registered repository unavailable")
        candidates = sorted((repository / ".dev" / "tasks").glob(f"{task_id}-*.md"))
        if len(candidates) != 1:
            raise Denied("expected one canonical task")
        spec_raw = _regular(candidates[0], 65536)
        doc = parse(spec_raw.decode("utf-8"))
        if validate(doc, candidates[0].name, project.company):
            raise Denied("canonical Gateway task failed validation")
        filed = [
            row
            for row in Journal(gateway_state / "journal.jsonl").entries()
            if row.get("kind") == "outcome"
            and row.get("outcome") == "filed"
            and row.get("project") == project_id
            and row.get("task_id") == task_id
            and row.get("request_id") == doc.get("request_id")
            and type(row.get("revision")) is int
            and row["revision"] >= 1
        ]
        if len(filed) != 1:
            raise Denied("canonical task lacks unique trusted Gateway filing")
        plan_raw = _regular(
            gateway_state / "cto-plans" / f"{project_id}-{task_id}.json", 32768
        )
        plan_schema = json.loads(
            _regular(gateway_root / ".dev" / "bin" / "plan.schema.json", 32768)
        )
        if list(Draft202012Validator(plan_schema).iter_errors(json.loads(plan_raw))):
            raise Denied("CTO plan failed schema validation")

        def decoder(raw: bytes) -> dict:
            if raw != spec_raw:
                raise Denied("canonical task bytes changed")
            return doc

        return GatewayInputs(repository, spec_raw, plan_raw, decoder)
    finally:
        sys.path.pop(0)
        sys.path.pop(0)
