#!/usr/bin/python3
"""Local-only, redacted Publisher Git preflight for the alfredpublish identity.

This file never invokes git push, reads a token, or writes Publisher evidence.
Install a pinned copy in /run before executing as alfredpublish on the host.
"""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import stat
import subprocess
import tempfile
from pathlib import Path


SOURCE = Path("/var/lib/alfred-draft-pr-evidence/T-0002/source.git")
BASELINE = "9000574c4c8807e84c4350e2fd342deeba341d7d"
FINAL = "89ba188f8a2f801d433a30c9c21363efb3e1043d"
ASKPASS = Path("/opt/alfred-draft-pr-publisher-v1/askpass.py")
TOKEN = Path("/var/lib/alfred-draft-pr-private/github-token")
GIT = "/usr/bin/git"


def _category(stderr: bytes) -> str:
    message = stderr.decode("utf-8", "replace").lower()
    if "dubious ownership" in message or "unsafe repository" in message:
        return "unsafe_repository_ownership"
    if "permission denied" in message or "could not open" in message:
        return "permission_denied"
    if "not our ref" in message or "unadvertised object" in message or "bad object" in message:
        return "missing_or_unadvertised_object"
    if "not a git repository" in message:
        return "not_a_git_repository"
    if "couldn't find remote ref" in message:
        return "revision_not_found"
    return "none" if not stderr else "other_redacted"


def _run(label: str, command: list[str], env: dict[str, str]) -> dict:
    try:
        result = subprocess.run(command, capture_output=True, stdin=subprocess.DEVNULL,
                                timeout=20, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"step": label, "passed": False, "exception": type(exc).__name__}
    return {"step": label, "passed": result.returncode == 0,
            "exit_code": result.returncode, "stderr_category": _category(result.stderr),
            "stderr_sha256": hashlib.sha256(result.stderr).hexdigest()}


def diagnose(source: Path = SOURCE, baseline: str = BASELINE, final: str = FINAL) -> dict:
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": str(ASKPASS),
           "ALFRED_PUBLISH_TOKEN_FILE": str(TOKEN),
           "GIT_ALLOW_PROTOCOL": "file", "GIT_PROTOCOL_FROM_USER": "0"}
    report: dict = {"identity_uid": os.geteuid(), "source": str(source), "steps": []}
    try:
        source_info = source.stat()
        report["source_access"] = {"owner_uid": source_info.st_uid,
                                    "group_gid": source_info.st_gid,
                                    "mode": oct(stat.S_IMODE(source_info.st_mode)),
                                    "readable": os.access(source / "HEAD", os.R_OK)}
    except OSError as exc:
        report["source_access"] = {"error": type(exc).__name__}
    with tempfile.TemporaryDirectory(prefix="alfred-publish-git-diagnostic-") as name:
        temporary = Path(name)
        temp_info = temporary.stat()
        report["temporary"] = {"owner_uid": temp_info.st_uid,
                               "mode": oct(stat.S_IMODE(temp_info.st_mode))}
        first = _run("git_init_bare", [GIT, "init", "--bare", "-q", str(temporary)], env)
        report["steps"].append(first)
        if first["passed"]:
            second = _run("git_fetch_local", [GIT, "-C", str(temporary), "fetch", "--no-tags",
                                              str(source), baseline, final], env)
            report["steps"].append(second)
            if not second["passed"] and second.get("stderr_category") == "unsafe_repository_ownership":
                # The local upload-pack child does not inherit a parent git -c
                # safe.directory override. A private, temporary global config
                # reaches both processes without changing host Git settings.
                safe_config = temporary / "diagnostic-gitconfig"
                safe_config.write_text(f"[safe]\n\tdirectory = {temporary}\n"
                                       f"\tdirectory = {source}\n")
                safe_config.chmod(0o600)
                safe_env = {**env, "GIT_CONFIG_GLOBAL": str(safe_config)}
                report["steps"].append(_run("git_fetch_with_ephemeral_safe_directory",
                    [GIT, "-C", str(temporary), "fetch", "--no-tags",
                     str(source), baseline, final], safe_env))
            if second["passed"]:
                helper = subprocess.run([GIT, "-C", str(temporary), "config", "--get-all",
                                         "credential.helper"], capture_output=True,
                                        stdin=subprocess.DEVNULL, timeout=20, env=env)
                report["push_environment"] = {
                    "askpass_executable": os.access(ASKPASS, os.X_OK),
                    "credential_helper_configured": bool(helper.stdout.strip()),
                    "git_config_injection_present": any(key.startswith("GIT_CONFIG_")
                                                        for key in os.environ),
                    "https_proxy_present": any(key in os.environ for key in
                                               ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")),
                }
                try:
                    token_info = TOKEN.stat()
                    report["push_environment"]["token_file"] = {
                        "owner_uid": token_info.st_uid,
                        "mode": oct(stat.S_IMODE(token_info.st_mode)),
                        "regular": stat.S_ISREG(token_info.st_mode)}
                except OSError as exc:
                    report["push_environment"]["token_file"] = {
                        "error": type(exc).__name__}
    return report


if __name__ == "__main__":
    if os.geteuid() != pwd.getpwnam("alfredpublish").pw_uid:
        raise SystemExit("Run only as alfredpublish")
    print(json.dumps(diagnose(), sort_keys=True))
