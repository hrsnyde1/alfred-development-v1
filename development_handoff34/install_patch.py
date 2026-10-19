"""handoff.34 overlay: Repo Intelligence. Alfred knows each project's repositories before
the Central CTO plans.

Owner-authorized 2026-10-19: "Before the CTO plans something, Alfred should already know
the repository." "I want to add this layer so we know all the repos that need to be
connected for each project." Choices: a deterministic scan plus a model summary written
from the facts only, cached per commit and refreshed after every change to main; a
project lists all its repositories and each task still changes only its own; the owner's
`.alfred/project.md` wins; relevant areas per request; previous Alfred changes from the
pipeline's own records.
- repo_intelligence.py (new): the scan, owner notes, summary, sealed per-commit store,
  history, relevant areas and the CTO block; `refresh` is the timer's job.
- schemas/repo-summary.schema.json (new): the summary's strict output schema.
- repos.json (new, /etc/alfred-development): every project's repositories, read only for
  planning; the primary one must be the policy's destination.
- role.py: the CTO plan step scans the exact planning snapshot and appends the block to
  the plan's planning_note (no plan schema change; the owner's grant binds it).
- pipeline.py and real_worker.py: each specialist gets the approved block as marked data
  inside the existing practices budget; both no-tools brokers gain answer().
- alfred-repo-intelligence.service / .timer (new): a sandboxed alfred oneshot every 10
  minutes. Then run `systemctl daemon-reload` and
  `systemctl enable --now alfred-repo-intelligence.timer`.
Installs only after handoff.33. Nothing restarts: the plan and developer stages run per
task. Rollback restores the three files and removes the new ones (disable the timer first).
"""

import argparse
import json
import os
import stat
import sys
from pathlib import Path

if __name__ == "__main__":
    sys.path.insert(0, "/usr/local/lib/alfred-fresh-v1")
from fresh_v1 import upgrade

LIBRARY = "/usr/local/lib/alfred-fresh-v1/fresh_v1/"
DEVELOPER = "/opt/alfred-developer-v1/developer_v1/"
UNITS = "/etc/systemd/system/"
CONFIG = "/etc/alfred-development/repos.json"
DESTINATIONS = {
    LIBRARY + "role.py": "fresh_v1/role.py",
    DEVELOPER + "pipeline.py": "developer_v1/pipeline.py",
    DEVELOPER + "real_worker.py": "developer_v1/real_worker.py",
    DEVELOPER + "repo_intelligence.py": "developer_v1/repo_intelligence.py",
    DEVELOPER + "schemas/repo-summary.schema.json": "developer_v1/schemas/repo-summary.schema.json",
    CONFIG: "development_handoff34/repos.json",
    UNITS + "alfred-repo-intelligence.service": "development_handoff34/alfred-repo-intelligence.service",
    UNITS + "alfred-repo-intelligence.timer": "development_handoff34/alfred-repo-intelligence.timer",
}
# Exactly the bytes installed through handoff.33 (main at 027971b), read from the host;
# None: a new file that must not exist yet.
BASE = {
    LIBRARY + "role.py": "bdcb9017d9bf56cacec72ccc52a68152bd864b7eee351167634870f15a425d52",
    DEVELOPER + "pipeline.py": "4034f55dfda08de718bf28b124bb2be7c6f218289041391051443dba8834ff10",
    DEVELOPER + "real_worker.py": "18050836a78c9715e07b6aa08ab4c449731cf1d760a48e29d9593bb00614f68c",
    DEVELOPER + "repo_intelligence.py": None,
    DEVELOPER + "schemas/repo-summary.schema.json": None,
    CONFIG: None,
    UNITS + "alfred-repo-intelligence.service": None,
    UNITS + "alfred-repo-intelligence.timer": None,
}
NEW_MODE = 0o644
# Unchanged code the changed files call into, as installed now.
DEPENDENCIES = {
    LIBRARY + "upgrade.py": "3eb50f78e901175439c9c812db07abb29b5d609593a63084968f933c400be492",
    LIBRARY + "protected.py": "573cc4c3032671eb8978997c07b5b34da4884a37c594117e608b671d2446233c",
    LIBRARY + "handoffs.py": "fe3023677b36f9d7a81148ebcb1877f00bc5e72d23a208de131f64da2e7f65cf",
    LIBRARY + "diagnostics.py": "57e155dc8ee141e58e55bac29e1b91cbbe677153092022b8d3ac2ef064e181b3",
    LIBRARY + "host.py": "a751647808c2f44254c559a9129e619a09f8a6d3bc675ce623d7749631f44950",
    "/usr/local/lib/alfred-fresh-v1/v1_cto/cto.py": "d60da3f6c230ef741c97f9689cd6fe85825b376c6e7029935165adb79b684ec1",
    DEVELOPER + "router.py": "aeb37188326f7ce6ffc7e51c2a288f13fb2520db20112e1381a31fcb86b4680c",
    DEVELOPER + "run_task.py": "4ba8a84261eee5e61384853848109e28ce53b7dce90aa7529e28b897fc3c3420",
    DEVELOPER + "execution.py": "06301833295c81a92e2f5390596407c9bbcf9dd92afafe8f0f5ce141d26bb989",
    DEVELOPER + "gateway_adapter.py": "64b1cb2a78614ca09e1e9166d5fae3c26bdec8d2bae0e733af0b0309f2274a8e",
    DEVELOPER + "owner_grants.py": "25c1ed5fbf94e34caf96e51c4efeec14092eba6103ea00924d501163a5161886",
    DEVELOPER + "team_skills.py": "5041bc94887bb165d35e93711969d21e958683001e7880215b7cb07cad7c3649",
    DEVELOPER + "team_snapshot.py": "db5e8d845e50399c24e275004f100df6e48b6ae3223f0e4debfb7218214985fa",
    DEVELOPER + "agent_profiles.py": "d9731eae53ffc27b4d453d946d044f2b93bde04e53e47fd9ba3221745149c775",
    DEVELOPER + "isolated_apply.py": "5a68ba29d6d8af3af640bc8df4735e32dea3f34a61bd07f36e42e957d21f1253",
    DEVELOPER + "schemas/model-edits.schema.json": "7697eaa2ae992bda00ae0d42e31d75b5807dea324d71ad1f7aafac4c08466d37",
}
BACKUP_SCHEMA = "alfred.development-handoff34-backup/1"


def paused(root):
    upgrade.validate_root(root)
    path = upgrade.target(root, "/home/alfred/Alfred/gateway/PAUSE")
    if not path.is_file():
        raise ValueError("operator PAUSE and idle workers required")


def checked(root, name, sha):
    path = upgrade.target(root, name)
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o022
        or upgrade.digest(path.read_bytes()) != sha
    ):
        raise ValueError("installed contract mismatch: " + str(path))
    return info, path.read_bytes()


def absent(root, name):
    path = upgrade.target(root, name)
    if os.path.lexists(path):
        raise ValueError("new file already exists: " + str(path))
    parent = path.parent.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
        raise ValueError("unprotected directory for new file: " + str(path.parent))


def rollback(root, backup):
    paused(root)
    info = backup.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("unprotected backup")
    index_path = backup / "index.json"
    index_info = index_path.lstat()
    if (
        not stat.S_ISREG(index_info.st_mode)
        or index_info.st_uid != os.geteuid()
        or index_info.st_nlink != 1
        or index_info.st_mode & 0o077
    ):
        raise ValueError("unprotected backup index")
    index = json.loads(index_path.read_bytes())
    if (
        index.get("schema") != BACKUP_SCHEMA
        or index.get("root") != str(root)
        or upgrade.marker(root) != index["activation_sha256"]
        or [e["path"] for e in index["files"]] != list(DESTINATIONS)
    ):
        raise ValueError("rollback inventory/root/activation mismatch")
    content = []
    for i, entry in enumerate(index["files"]):
        if entry["sha256"] != BASE[entry["path"]]:
            raise ValueError("rollback backup contract mismatch")
        if entry["sha256"] is None:
            content.append(None)
            continue
        if entry["backup"] != "file-" + str(i):
            raise ValueError("rollback backup contract mismatch")
        path = backup / entry["backup"]
        stored = path.lstat()
        if (not stat.S_ISREG(stored.st_mode) or stored.st_uid != os.geteuid()
                or upgrade.digest(path.read_bytes()) != entry["sha256"]):
            raise ValueError("rollback backup contract mismatch")
        content.append(path.read_bytes())
    for entry, raw in reversed(list(zip(index["files"], content, strict=True))):
        target = upgrade.target(root, entry["path"])
        if raw is None:
            if os.path.lexists(target):
                target.unlink()
        else:
            upgrade.atomic(target, raw, entry["uid"], entry["gid"], entry["mode"])
    if upgrade.marker(root) != index["activation_sha256"]:
        raise ValueError("activation marker changed")
    return {"status": "ROLLED_BACK_HELD", "service_action": "systemctl daemon-reload"}


def install(release, pin, root, backup, *, fail_after=None):
    paused(root)
    verified = upgrade.verify(release, pin)
    content = {n: (release / n).read_bytes() for n in DESTINATIONS.values()}
    if any(upgrade.digest(raw) != verified[n] for n, raw in content.items()):
        raise ValueError("release changed after verification")
    previous = {}
    for name, sha in BASE.items():
        if sha is None:
            absent(root, name)
            previous[name] = None
        else:
            previous[name] = checked(root, name, sha)
    for name, sha in DEPENDENCIES.items():
        checked(root, name, sha)
    activation = upgrade.marker(root)
    backup.mkdir(mode=0o700, parents=False, exist_ok=False)
    entries = []
    for i, (name, value) in enumerate(previous.items()):
        if value is None:
            entries.append({"path": name, "backup": None, "sha256": None})
            continue
        info, raw = value
        item = "file-" + str(i)
        upgrade.atomic(backup / item, raw, os.geteuid(), os.getegid(), 0o600)
        entries.append(
            {
                "path": name,
                "backup": item,
                "sha256": upgrade.digest(raw),
                "uid": info.st_uid,
                "gid": info.st_gid,
                "mode": stat.S_IMODE(info.st_mode),
            }
        )
    upgrade.atomic(
        backup / "index.json",
        (
            json.dumps(
                {
                    "schema": BACKUP_SCHEMA,
                    "root": str(root),
                    "activation_sha256": activation,
                    "files": entries,
                },
                sort_keys=True,
            )
            + "\n"
        ).encode(),
        os.geteuid(),
        os.getegid(),
        0o600,
    )
    try:
        for i, (name, source) in enumerate(DESTINATIONS.items()):
            if i == fail_after:
                raise OSError("disposable fixture fault")
            if previous[name] is None:
                upgrade.atomic(upgrade.target(root, name), content[source],
                               os.geteuid(), os.getegid(), NEW_MODE)
            else:
                info, _ = previous[name]
                upgrade.atomic(
                    upgrade.target(root, name),
                    content[source],
                    info.st_uid,
                    info.st_gid,
                    stat.S_IMODE(info.st_mode),
                )
        if upgrade.marker(root) != activation:
            raise ValueError("activation marker changed")
    except BaseException:
        rollback(root, backup)
        raise
    return {
        "status": "INSTALLED_HELD",
        "service_action": "systemctl daemon-reload",
        "next": "systemctl enable --now alfred-repo-intelligence.timer",
        "retry_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "verify", "rollback"))
    parser.add_argument("--release", type=Path)
    parser.add_argument("--manifest")
    parser.add_argument("--root", type=Path, default=Path("/"))
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.action == "verify":
        result = {"files": len(upgrade.verify(args.release, args.manifest))}
    elif args.action == "install":
        result = install(args.release, args.manifest, args.root, args.backup)
    else:
        result = rollback(args.root, args.backup)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
