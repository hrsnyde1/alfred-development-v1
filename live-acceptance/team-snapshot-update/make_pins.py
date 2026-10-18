"""Regenerate the team-snapshot update pins (reads only; writes only beside this file).

    python3 live-acceptance/team-snapshot-update/make_pins.py

installed-before.sha256 records the host's current bytes (paths relative to /).
staged.sha256 pins the checkout files to copy (paths relative to the checkout).
installed-after.sha256 is staged.sha256 at the host paths (relative to /).
"""

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
DEVELOPER = ("README.md", "execution.py", "models.codex-verified.example.json", "pipeline.py",
             "real_worker.py", "router.py", "run_task.py", "specialists.json",
             "schemas/developer-report.schema.json", "release.sha256")
FRESH = ("fresh_v1/host.py", "fresh_v1/role.py", "v1_cto/plan.schema.json")
CHECKER = "live-acceptance/verify_team_snapshot_host_update.py"


def host_path(staged: str) -> str:
    if staged.startswith("developer_v1/"):
        return "opt/alfred-developer-v1/" + staged
    return "usr/local/lib/alfred-fresh-v1/" + staged


def line(root: Path, relative: str) -> str:
    return f"{hashlib.sha256((root / relative).read_bytes()).hexdigest()}  {relative}\n"


def main() -> None:
    replaced = [f"developer_v1/{name}" for name in DEVELOPER] + list(FRESH)
    staged = replaced + ["developer_v1/team_snapshot.py"]
    (HERE / "installed-before.sha256").write_text(
        "".join(line(Path("/"), host_path(p)) for p in replaced))
    (HERE / "staged.sha256").write_text(
        "".join(line(CHECKOUT, p) for p in [*staged, CHECKER]))
    (HERE / "installed-after.sha256").write_text(
        "".join(line(CHECKOUT, p).replace(f"  {p}", f"  {host_path(p)}") for p in staged))


if __name__ == "__main__":
    main()
