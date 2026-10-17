"""Requester intake filer and outbox. The only code that touches a requester's intake folder.

  uv run python .dev/bin/intake.py --outbox T-0007 # write outbox/T-0007.status.json

The Development Gateway (`.dev/bin/gateway.py`, ADR 0003) uses `IntakeFiler` to turn
validated `alfred.devreq/1` envelopes into specs in the registered project's repository,
stamped with the requester its intake folder is bound to (`alfred.gateway.requesters`,
T-0010: Hermes). For those specs `--outbox` also appends a status event to
outbox/<request_id>/.

The legacy command that filed every spec in the OpenClaw inbox is retired (T-0010): running
this script without `--outbox` refuses, and `run_intake` below is not reachable from any
command. It stays only so old behavior can be tested.

Inbox files are untrusted data. Each one is size-capped, parsed (Markdown spec or JSON in
the schema's normalised form), stamped with the requester's source, validated, and written to
.dev/tasks/ as `proposed`. Nothing in an inbox file is ever executed, and an inbox file
cannot choose its own status, approval, risk, branch, PR, id or source. Processed files move
to processed/; invalid ones move to rejected/ with a .reason.txt.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import yaml
from taskspec import (
    MAX_BYTES,
    REPO_COMPANY,
    TASKS_DIR,
    SpecError,
    mentions_protected,
    next_id,
    parse,
    render,
    slugify,
    validate,
)

from alfred.gateway.dispatcher import (
    FilingError,
    GatewayError,
    gateway_lock,
    pin_outbox,
)
from alfred.gateway.envelope import Envelope
from alfred.gateway.events import SPEC_STATUS_EVENTS, Outbox, write_json_atomic
from alfred.gateway.journal import Journal, JournalError
from alfred.gateway.requesters import (
    RequesterError,
    default_intake_dir,
    require_bound_requester,
)
from alfred.registry.loader import Project

# The only intake folder bound to a requester (T-0010). The environment does not move it.
DEFAULT_INTAKE = default_intake_dir()
# Dispatcher state (journal, PAUSE). Not mounted into OpenClaw (ADR 0003).
DEFAULT_GATEWAY = Path(
    os.environ.get("ALFRED_GATEWAY_DIR", str(Path.home() / "Alfred" / "gateway"))
)
DRAFT_SECTIONS = (
    "objective",
    "scope",
    "requirements",
    "constraints",
    "acceptance_criteria",
    "security_considerations",
    "testing_requirements",
)


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise SpecError("symlinks are not accepted")
    if path.stat().st_size > MAX_BYTES:
        raise SpecError(f"file is larger than {MAX_BYTES} bytes")
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        doc = json.loads(text)
        if not isinstance(doc, dict):
            raise SpecError("JSON spec must be an object")
        return doc
    if path.suffix == ".md":
        return parse(text)
    raise SpecError("only .md and .json specs are accepted")


def stamp(
    doc: dict[str, Any],
    new_id: str,
    original_name: str,
    today: str,
    *,
    source: str,
    company: str | None = None,
    project: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Apply intake rules: the requester controls content, never workflow fields.

    `source`, `company`, `project` and `request_id` come from the trusted gateway (the intake
    folder's binding, the registry and the validated envelope), never from the inbox file itself.
    """
    sections = dict(doc.get("sections") or {})
    sections["implementation_notes"] = "(Written by the CTO during planning.)"
    sections["log"] = f"- {today} received from {source} ({original_name}); proposed"
    stamped: dict[str, Any] = {
        "id": new_id,
        "title": doc.get("title"),
        "status": "proposed",
        "source": source,
        "risk": "high" if mentions_protected({**doc, "sections": sections}) else None,
        "company": company or doc.get("company", REPO_COMPANY),
        "created": today,
        "approved_by": None,
        "branch": None,
        "pr": None,
        "sections": sections,
    }
    if project is not None:
        stamped["project"] = project
    if request_id is not None:
        stamped["request_id"] = request_id
    return stamped


class IntakeFiler:
    """Builds, validates and writes gateway specs (the dispatcher's `SpecFiler`).

    The dispatcher has already checked that `tasks_dir` is the registered project's own,
    non-symlinked `.dev/tasks/`. This class only turns content into a `proposed` spec.
    """

    def file_envelope(
        self,
        envelope: Envelope,
        project: Project,
        tasks_dir: Path,
        today: str,
        *,
        source: str,
    ) -> str:
        with _locked_tasks_dir(tasks_dir):
            existing = _spec_for_request(tasks_dir, envelope.request_id)
            draft = envelope.draft
            content = {
                "title": draft.title,
                "sections": {key: getattr(draft, key).strip() for key in DRAFT_SECTIONS},
            }
            if existing is not None:  # crash after publication: never refile
                task_id, old = existing
                if (
                    old.get("project") != project.id
                    or old.get("company") != project.company
                    or old.get("source") != source
                    or old.get("title") != content["title"]
                    or any(
                        old.get("sections", {}).get(k) != v for k, v in content["sections"].items()
                    )
                ):
                    raise FilingError(
                        "request ID already filed with different content or authority"
                    )
                return task_id
            note = f"request {envelope.request_id}, revision {envelope.revision}, {draft.task_type}"
            try:
                new_id = next_id(tasks_dir)
            except SpecError as exc:
                raise FilingError(str(exc)) from exc
            doc = stamp(
                content,
                new_id,
                note,
                today,
                source=source,
                company=project.company,
                project=project.id,
                request_id=envelope.request_id,
            )
            return _write_spec(doc, tasks_dir, project.company)

    def file_legacy(
        self,
        text: str,
        suffix: str,
        tasks_dir: Path,
        today: str,
        *,
        company: str,
        project: str,
        source: str,
    ) -> str:
        try:
            if suffix == ".json":
                raw = json.loads(text)
                if not isinstance(raw, dict):
                    raise FilingError("JSON spec must be an object")
                content: dict[str, Any] = raw
            elif suffix == ".md":
                content = parse(text)
            else:
                raise FilingError("only .md and .json specs are accepted")
        except (SpecError, ValueError, yaml.YAMLError) as exc:
            raise FilingError(str(exc)) from exc
        if not isinstance(content.get("sections"), dict):
            raise FilingError("sections must be an object")
        sections = {
            k: v.strip() if isinstance(v, str) else v for k, v in content["sections"].items()
        }
        with _locked_tasks_dir(tasks_dir):
            try:
                new_id = next_id(tasks_dir)
            except SpecError as exc:
                raise FilingError(str(exc)) from exc
            doc = stamp(
                {**content, "sections": sections},
                new_id,
                "legacy inbox file",
                today,
                source=source,
                project=project,
            )
            return _write_spec(doc, tasks_dir, company)


@contextmanager
def _locked_tasks_dir(tasks_dir: Path):
    """Serialize all Gateway filers for this repository without creating a lock file."""
    fd = os.open(tasks_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _spec_for_request(tasks_dir: Path, request_id: str) -> tuple[str, dict[str, Any]] | None:
    """Return the id of the spec already filed for `request_id` in `tasks_dir`, if any.

    Only the parsed front matter counts: section text comes from the requester and must
    never decide whether a request is already filed.
    """
    found: tuple[str, dict[str, Any]] | None = None
    for path in sorted(tasks_dir.glob("T-[0-9][0-9][0-9][0-9]-*.md")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            doc = parse(path.read_text(encoding="utf-8"))
        except (SpecError, yaml.YAMLError, UnicodeDecodeError):
            continue
        if doc.get("request_id") == request_id and doc.get("id") == path.name[:6]:
            if found is not None:
                raise FilingError("request ID occurs in multiple task specs")
            found = (path.name[:6], doc)
    return found


def _write_spec(doc: dict[str, Any], tasks_dir: Path, company: str) -> str:
    """Validate `doc` and create it in `tasks_dir`; never overwrites or follows a link."""
    name = f"{doc['id']}-{slugify(str(doc['title'] or ''))}.md"
    errors = validate(doc, name, company)
    if errors:
        raise FilingError("; ".join(errors))
    text = render(doc)
    try:
        round_trip = parse(text)
    except (SpecError, yaml.YAMLError) as exc:
        raise FilingError(f"draft does not render to a valid spec: {exc}") from exc
    if round_trip != doc:
        raise FilingError("draft text changes the spec structure (headings or front matter)")
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise FilingError("rendered task spec exceeds size limit")
    temporary: str | None = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".gateway-", suffix=".tmp", dir=tasks_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o644)
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.link(temporary, tasks_dir / name, follow_symlinks=False)
        directory_fd = os.open(tasks_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise FilingError(f"cannot durably publish task spec: {exc.strerror}") from exc
    finally:
        if temporary is not None:
            os.unlink(temporary)
    return str(doc["id"])


def run_intake(intake_dir: Path, tasks_dir: Path, today: str) -> tuple[list[Path], list[Path]]:
    """RETIRED (T-0010): files an inbox as legacy `openclaw` specs. No command reaches it."""
    inbox = intake_dir / "inbox"
    filed: list[Path] = []
    rejected: list[Path] = []
    for sub in ("processed", "rejected", "outbox"):
        (intake_dir / sub).mkdir(parents=True, exist_ok=True)
    for src in sorted(p for p in inbox.iterdir() if not p.name.startswith(".")):
        try:
            doc = stamp(_load(src), next_id(tasks_dir), src.name, today, source="openclaw")
            name = f"{doc['id']}-{slugify(str(doc['title'] or ''))}.md"
            errors = validate(doc, name)
            if errors:
                raise SpecError("; ".join(errors))
            dest = tasks_dir / name
            dest.write_text(render(doc), encoding="utf-8")
            shutil.move(str(src), str(intake_dir / "processed" / src.name))
            filed.append(dest)
        except (SpecError, ValueError, OSError, yaml.YAMLError) as exc:
            target = intake_dir / "rejected" / src.name
            shutil.move(str(src), str(target))
            (intake_dir / "rejected" / f"{src.name}.reason.txt").write_text(
                f"{exc}\n", encoding="utf-8"
            )
            rejected.append(target)
    return filed, rejected


def write_outbox(
    task_id: str, intake_dir: Path, tasks_dir: Path, gateway_dir: Path | None = None
) -> Path:
    """Write outbox/T-NNNN.status.json; for gateway specs also emit a status event.

    OpenClaw can write the outbox, so nothing there is read and no symlink is followed.
    """
    matches = sorted(tasks_dir.glob(f"{task_id}-*.md"))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one spec for {task_id}, found {len(matches)}")
    doc = parse(matches[0].read_text(encoding="utf-8"))
    status = {
        "id": doc["id"],
        "status": doc["status"],
        "branch": doc.get("branch"),
        "pr": doc.get("pr"),
        "updated": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    outbox = intake_dir / "outbox"
    fd = pin_outbox(intake_dir)  # refuses a symlinked dev-requests/ or outbox/
    try:
        write_json_atomic(fd, f"{task_id}.status.json", json.dumps(status, indent=2) + "\n")
        request_id = doc.get("request_id")
        if request_id:
            gateway = gateway_dir or DEFAULT_GATEWAY
            pr = doc.get("pr")
            with gateway_lock(gateway):
                events = Journal(gateway / "journal.jsonl").record_event(
                    request_id=str(request_id),
                    event=SPEC_STATUS_EVENTS[str(doc["status"])],
                    task_id=str(doc["id"]),
                    project=doc.get("project"),
                    summary=f"{doc['id']} is {doc['status']}",
                    links=[str(pr)] if pr else (),
                )
                Outbox(outbox, outbox_fd=fd).publish(str(request_id), events)
    finally:
        os.close(fd)
    return outbox / f"{task_id}.status.json"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outbox", metavar="TASK_ID")
    ap.add_argument("--intake-dir", type=Path, default=DEFAULT_INTAKE)
    ap.add_argument("--tasks-dir", type=Path, default=TASKS_DIR)
    ap.add_argument("--gateway-dir", type=Path, default=DEFAULT_GATEWAY)
    args = ap.parse_args(argv)
    if args.intake_dir != DEFAULT_INTAKE:
        try:
            require_bound_requester(args.intake_dir)
        except RequesterError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
    if args.outbox:
        try:
            out = write_outbox(args.outbox, args.intake_dir, args.tasks_dir, args.gateway_dir)
        except (GatewayError, JournalError, OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(out)
        return 0
    print(
        "refused: this command filed the OpenClaw inbox and is retired (T-0010); "
        "file requests with `gateway.py run-once` (Hermes intake folder)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
