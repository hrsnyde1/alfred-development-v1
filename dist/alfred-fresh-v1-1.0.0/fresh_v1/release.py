"""Build a deterministic, inventoried V1 integration release from staging only."""

import argparse
import gzip
import hashlib
import io
import json
import shutil
import tarfile
from pathlib import Path

VERSION = "1.0.0"


def build(source, output):
    name = "alfred-fresh-v1-" + VERSION
    directory = output / name
    directory.mkdir(parents=True, exist_ok=False)
    files = set()
    for relative in ("fresh_v1", "developer_v1"):
        for path in (source / relative).rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and path.suffix in {".py", ".json", ".sha256", ".conf"}
            ):
                files.add(path.relative_to(source))
    # Test-only copies of existing worker code; upgrade.mapping never installs
    # these packages. This makes the mocked integration tests reproducible.
    for relative in (
        "independent_qa",
        "independent_reviewer",
        "draft_pr_publisher",
        "completion_integration",
    ):
        for path in (source / relative).rglob("*"):
            if (
                path.is_file()
                and "__pycache__" not in path.parts
                and (path.suffix == ".py" or path.name.endswith(".schema.json"))
            ):
                files.add(path.relative_to(source))
    # Include the complete Developer inventory, including its pinned README.
    for line in (source / "developer_v1/release.sha256").read_text().splitlines():
        files.add(Path(line.split("  ", 1)[1]))
    files.update(
        map(
            Path,
            [
                "v1_cto/cto.py",
                "v1_cto/plan.schema.json",
                "FRESH_V1_HOST.md",
                "tests/test_fresh_v1.py",
                "tests/test_fresh_v1_release.py",
                "tests/conftest.py",
                "tests/test_draft_pr_publisher.py",
                "tests/test_independent_qa.py",
                "tests/test_independent_reviewer.py",
                "v1_1a/fixture/registry.template.yaml",
                "v1_1a/fixture/dev-001/.dev/tasks/.gitkeep",
            ],
        )
    )
    for relative in sorted(files):
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    # Read-only host contract: installed code hashes only, never credentials.
    old = [
        "/opt/alfred-developer-v1/developer_v1/" + n
        for n in (
            "pipeline.py",
            "owner_grants.py",
            "run_task.py",
            "publication_approval.py",
            "trusted_intake_development.py",
            "release.sha256",
        )
    ]
    old += [
        "/usr/local/lib/alfred-v1.1/trusted_intake.py",
        "/home/alfred/Git/alfred/.dev/bin/cto.py",
        "/home/alfred/Git/alfred/.dev/bin/plan.schema.json",
        "/opt/alfred-draft-pr-publisher-v1/worker.py",
        "/opt/alfred-independent-qa-v1/independent_qa/worker.py",
        "/opt/alfred-reviewer-v1/independent_reviewer/worker.py",
        "/usr/local/lib/alfred-completion-v1/completion_integration/runtime.py",
    ]
    contract = {
        "schema": "alfred.fresh-v1-host-contract/1",
        "version": VERSION,
        "installed_sha256": {
            p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in old
        },
    }
    (directory / "host-contract.json").write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n"
    )
    inventory = [
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(directory)}\n"
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    ]
    manifest = "".join(inventory).encode()
    (directory / "MANIFEST.sha256").write_bytes(manifest)
    archive = output / (name + ".tar.gz")
    with (
        archive.open("xb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
        tarfile.open(fileobj=compressed, mode="w") as tar,
    ):
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            data = path.read_bytes()
            info = tarfile.TarInfo(name + "/" + str(path.relative_to(directory)))
            info.size, info.mode, info.mtime = len(data), 0o644, 0
            tar.addfile(info, io.BytesIO(data))
    sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / (archive.name + ".sha256")).write_text(sha + "  " + archive.name + "\n")
    return {
        "archive": str(archive),
        "sha256": sha,
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "files": len(inventory),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output)))
