"""Approved team skills for the Central CTO's specialists. Standard library only.

Skills come only from a root-owned snapshot of the merged hrsnyde1/alfred-team-skills
library at one pinned commit:

    /usr/local/lib/alfred-team-skills/cto/ACTIVE            the commit new plans use
    /usr/local/lib/alfred-team-skills/cto/<commit>/         one immutable snapshot
        MANIFEST.json                                       commit and SHA-256 of every file
        roles.json, skills/<id>/SKILL.md, skills/<id>/adoption.json

The owner's library tool (scripts/team_skills_deploy.py in that repository, run as root
from the pinned commit) writes snapshots. This module never writes. It re-checks
ownership, the manifest and the library's own format and safety rules every time it
loads, so a snapshot that was altered, or a skill that the library validator would now
refuse, fails closed.

The CTO plan records the selected skill ids and SHA-256 digests. The owner's development
grant binds the plan digest, so the approved plan fixes exactly which skill text the
specialists receive. The Developer reloads that same commit and refuses any difference.
Without an ACTIVE file the plan has no team_skills field and nothing changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .router import Denied

ROOT = Path("/usr/local/lib/alfred-team-skills/cto")
ROLE = "cto"
SNAPSHOT_SCHEMA = "alfred.team-skills-snapshot/1"
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
SKILL_FILES = ("SKILL.md", "adoption.json")
MAX_FILE = 16_384
MAX_SKILLS = 64

# The library validator's rules (alfred-team-skills scripts/validate.py). They are copied
# here, inside this hash-pinned release, so a library change cannot loosen what the
# pipeline accepts. tests/test_team_skills.py checks they still match the library.
ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
KINDS = ("skill", "concept")
VERDICTS = ("adopt", "adapt")
MAX_SKILL_BYTES = 12_000
FORBIDDEN = [
    (re.compile(r"(?i)\b(curl|wget)\b[^\n|]*\|\s*(ba|z)?sh\b"), "pipes a download into a shell"),
    (re.compile(r"(?i)\bignore (all |any )?(previous|prior|above) (instructions|rules)"), "tries to override instructions"),
    (re.compile(r"(?i)\b(disregard|bypass|disable)\b[^\n]{0,40}\b(safety|guard|approval|sandbox|rules?)\b"), "tries to bypass safeguards"),
    (re.compile(r"(?i)\b(api[_ -]?key|secret|password|private key|access token|bearer)\b[^\n]{0,60}\b(send|post|upload|print|echo|export)\b"),
     "handles credentials"),
    (re.compile(r"(?i)\b(send|post|upload|exfiltrate)\b[^\n]{0,60}\b(api[_ -]?key|secret|password|token|credential)"), "handles credentials"),
    (re.compile("[​-‏‪-‮⁠-⁤﻿]"), "contains hidden/bidirectional characters"),
    (re.compile(r"[A-Za-z0-9+/]{200,}={0,2}"), "contains a long encoded blob"),
]


@dataclass(frozen=True)
class Skill:
    id: str
    title: str
    body: str
    sha256: str
    tokens: int
    specialists: tuple[str, ...]
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class Library:
    commit: str
    budget_tokens: int
    skills: tuple[Skill, ...]


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with --- front matter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md front matter is not closed")
    fields = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip() or key.strip() in fields:
            raise ValueError("bad front matter line")
        fields[key.strip()] = value.strip().strip('"')
    return fields, text[end + 5:]


def screen(text: str) -> list[str]:
    return sorted({reason for pattern, reason in FORBIDDEN if pattern.search(text)})


def _read(path: Path, owner: int) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise Denied("team skill snapshot file is unavailable: " + path.name) from exc
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner
                or info.st_mode & 0o022 or info.st_size > MAX_FILE):
            raise Denied("team skill snapshot file is not protected: " + path.name)
        return os.read(fd, MAX_FILE + 1)
    finally:
        os.close(fd)


def _directory(path: Path, owner: int) -> None:
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022:
        raise Denied("team skill snapshot directory is not protected")


def active_commit(root: Path = ROOT, *, owner: int = 0) -> str | None:
    """The commit new plans use, or None when the owner has not enabled team skills."""
    if not os.path.lexists(root / "ACTIVE"):
        return None
    _directory(root, owner)
    commit = _read(root / "ACTIVE", owner).decode("ascii", "replace").strip()
    if not COMMIT.fullmatch(commit):
        raise Denied("team skill ACTIVE pin is invalid")
    return commit


def _check_skill(sid: str, skill_raw: bytes, meta_raw: bytes, roles: dict,
                 specialists: set[str]) -> Skill:
    """Same checks as the library validator, plus role and applies_to for the CTO."""
    if not ID.match(sid) or len(skill_raw) > MAX_SKILL_BYTES:
        raise Denied("team skill " + sid + " fails the library format")
    try:
        text = skill_raw.decode("utf-8")
        fields, body = front_matter(text)
        meta = json.loads(meta_raw)
    except (UnicodeDecodeError, ValueError) as exc:
        raise Denied("team skill " + sid + " cannot be parsed") from exc
    review = meta.get("review") if type(meta) is dict else None
    source = meta.get("source") if type(meta) is dict else None
    if (fields.get("name") != sid or not 20 <= len(fields.get("description", "")) <= 400
            or len(body.strip()) < 80 or screen(text) or type(review) is not dict
            or type(source) is not dict or meta.get("id") != sid
            or meta.get("kind") not in KINDS or type(meta.get("roles")) is not list
            or not meta["roles"] or any(r not in roles for r in meta["roles"])
            or (not COMMIT.fullmatch(str(source.get("commit", ""))) and source.get("type") != "article")
            or not str(source.get("url", "")).startswith("https://")
            or review.get("verdict") not in VERDICTS
            or any(len(str(review.get(k, ""))) < 20 for k in ("benefit", "reason"))
            or review.get("screen_flags")):
        raise Denied("team skill " + sid + " fails the library rules")
    if ROLE not in meta["roles"]:
        raise Denied("team skill " + sid + " is not approved for the CTO")
    applies = meta.get("applies_to", {})
    if type(applies) is not dict or set(applies) - {"specialists", "keywords"}:
        raise Denied("team skill " + sid + " applies_to is invalid")
    chosen = applies.get("specialists", [])
    keywords = applies.get("keywords", [])
    if (type(chosen) is not list or any(s not in specialists for s in chosen)
            or type(keywords) is not list
            or any(type(k) is not str or not 2 <= len(k) <= 40 for k in keywords)):
        raise Denied("team skill " + sid + " applies_to is invalid")
    return Skill(sid, str(meta.get("title") or sid)[:120], body.strip(), _digest(skill_raw),
                 estimate_tokens(body), tuple(chosen), tuple(k.lower() for k in keywords))


def load(commit: str, root: Path = ROOT, *, owner: int = 0) -> Library:
    """Verify one snapshot completely; any difference from its manifest fails closed."""
    if not COMMIT.fullmatch(commit):
        raise Denied("team skill commit is invalid")
    _directory(root, owner)
    base = root / commit
    if not os.path.lexists(base):
        raise Denied("team skill snapshot for the approved commit is missing")
    _directory(base, owner)
    try:
        manifest = json.loads(_read(base / "MANIFEST.json", owner))
    except ValueError as exc:
        raise Denied("team skill manifest is invalid") from exc
    files = manifest.get("files") if type(manifest) is dict else None
    if (type(manifest) is not dict or manifest.get("schema") != SNAPSHOT_SCHEMA
            or manifest.get("commit") != commit or manifest.get("role") != ROLE
            or type(files) is not dict or "roles.json" not in files):
        raise Denied("team skill manifest is invalid")
    actual = set()
    for directory, dirs, names in os.walk(base):
        for name in dirs:
            _directory(Path(directory) / name, owner)
        for name in names:
            actual.add((Path(directory) / name).relative_to(base).as_posix())
    if actual != set(files) | {"MANIFEST.json"}:
        raise Denied("team skill snapshot has unlisted or missing files")
    content = {}
    for relative, digest in files.items():
        data = _read(base / relative, owner)
        if _digest(data) != digest:
            raise Denied("team skill snapshot file differs from its manifest")
        content[relative] = data
    try:
        roles = json.loads(content["roles.json"])["roles"]
        budget = roles[ROLE]["budget_tokens"]
    except (ValueError, KeyError, TypeError) as exc:
        raise Denied("team skill roles are invalid") from exc
    if type(budget) is not int or budget <= 0:
        raise Denied("team skill budget is invalid")
    specialists = set(roles[ROLE].get("specialists", []))
    ids = sorted({Path(p).parts[1] for p in files if p.startswith("skills/")})
    if len(ids) > MAX_SKILLS or set(files) != {"roles.json"} | {
            f"skills/{sid}/{name}" for sid in ids for name in SKILL_FILES}:
        raise Denied("team skill snapshot layout is invalid")
    skills = tuple(_check_skill(sid, content[f"skills/{sid}/SKILL.md"],
                                content[f"skills/{sid}/adoption.json"], roles, specialists)
                   for sid in ids)
    if sum(s.tokens for s in skills) > budget:
        raise Denied("team skills exceed the CTO token budget")
    return Library(commit, budget, skills)


def select(library: Library, spec: dict, specialists: list[str]) -> list[Skill]:
    """A skill applies when it names none of the filters, or matches one of them."""
    sections = spec.get("sections") or {}
    text = " ".join(str(x) for x in (spec.get("title", ""), sections.get("objective", ""))).lower()
    chosen = []
    for skill in library.skills:
        general = not skill.specialists and not skill.keywords
        if (general or set(skill.specialists) & set(specialists)
                or any(k in text for k in skill.keywords)):
            chosen.append(skill)
    return chosen


def plan_record(library: Library, skills: list[Skill]) -> dict:
    return {"library_commit": library.commit, "role": ROLE,
            "skills": [{"id": s.id, "title": s.title, "sha256": s.sha256, "tokens": s.tokens}
                       for s in skills]}


def attach(plan: dict, spec: dict, specialists: list[str], root: Path = ROOT, *,
           owner: int = 0) -> dict:
    """Planning: record the matching skills from the ACTIVE snapshot in the plan."""
    commit = active_commit(root, owner=owner)
    if commit is not None:
        library = load(commit, root, owner=owner)
        plan["team_skills"] = plan_record(library, select(library, spec, specialists))
    return plan


def for_plan(plan: dict, root: Path = ROOT, *, owner: int = 0) -> list[dict]:
    """Development: the approved plan's skill text, verified against its recorded digests."""
    record = plan.get("team_skills")
    if record is None:
        return []
    if (type(record) is not dict or set(record) != {"library_commit", "role", "skills"}
            or record["role"] != ROLE or type(record["skills"]) is not list):
        raise Denied("plan team_skills record is invalid")
    if not record["skills"]:
        return []
    library = load(record["library_commit"], root, owner=owner)
    by_id = {s.id: s for s in library.skills}
    result = []
    for entry in record["skills"]:
        skill = by_id.get(entry.get("id")) if type(entry) is dict else None
        if skill is None or entry != {"id": skill.id, "title": skill.title,
                                      "sha256": skill.sha256, "tokens": skill.tokens}:
            raise Denied("approved team skill differs from the pinned library")
        result.append({"id": skill.id, "title": skill.title, "instructions": skill.body})
    if sum(estimate_tokens(s["instructions"]) for s in result) > library.budget_tokens:
        raise Denied("team skills exceed the CTO token budget")
    return result
