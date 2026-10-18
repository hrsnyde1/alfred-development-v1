"""Regenerate the passkey-approval update pins (reads only; writes only beside this file).

    python3 live-acceptance/passkey-approval-update/make_pins.py

installed-before.sha256: the host's current bytes of every file replaced (paths relative
to /). Files the update adds are checked absent by the procedure instead.
staged.sha256: the checkout files to copy (paths relative to the checkout), including the
checker and its throwaway-passkey fixture.
installed-after.sha256: every installed file after the update, at its host path.
"""

import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
DEV = "opt/alfred-developer-v1/developer_v1/"
# host path (relative to /) -> checkout source
REPLACED = {
    DEV + "owner_grants.py": "developer_v1/owner_grants.py",
    DEV + "publication_approval.py": "developer_v1/publication_approval.py",
    DEV + "trusted_intake_development.py": "developer_v1/trusted_intake_development.py",
    DEV + "stage_approval.py": "developer_v1/stage_approval.py",
    DEV + "stage_publication.py": "developer_v1/stage_publication.py",
    DEV + "pipeline.py": "developer_v1/pipeline.py",
    DEV + "README.md": "developer_v1/README.md",
    DEV + "release.sha256": "developer_v1/release.sha256",
    "usr/local/lib/alfred-v1.1/trusted_intake.py": "developer_v1/trusted_intake_development.py",
    "usr/local/lib/alfred-fresh-v1/fresh_v1/host.py": "fresh_v1/host.py",
}
ADDED = {
    DEV + "owner_passkey.py": "developer_v1/owner_passkey.py",
    DEV + "owner_approval.py": "developer_v1/owner_approval.py",
    DEV + "enroll_owner_passkey.py": "developer_v1/enroll_owner_passkey.py",
    DEV + "alfred-development-intake-owner-approval.conf":
        "developer_v1/alfred-development-intake-owner-approval.conf",
    "etc/systemd/system/alfred-development-intake.service.d/50-owner-approvals.conf":
        "developer_v1/alfred-development-intake-owner-approval.conf",
}
CHECKER = ("live-acceptance/verify_owner_passkey_host_update.py",
           "live-acceptance/owner_passkey_fixture.py")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    (HERE / "installed-before.sha256").write_text(
        "".join(f"{sha(Path('/') / host)}  {host}\n" for host in REPLACED))
    sources = sorted(set(REPLACED.values()) | set(ADDED.values()) | set(CHECKER))
    (HERE / "staged.sha256").write_text(
        "".join(f"{sha(CHECKOUT / source)}  {source}\n" for source in sources))
    (HERE / "installed-after.sha256").write_text(
        "".join(f"{sha(CHECKOUT / source)}  {host}\n"
                for host, source in {**REPLACED, **ADDED}.items()))


if __name__ == "__main__":
    main()
