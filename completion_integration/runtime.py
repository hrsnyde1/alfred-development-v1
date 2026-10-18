"""On-demand adapter. No listener, Photon SDK connection, scheduler, or Gateway."""

import argparse
import hashlib
import http.client
import json
import os
import re
import stat
import subprocess
from pathlib import Path

from jsonschema import ValidationError

from .completion import prepare
from .delivery import DeliveryTracker, DeliveryTrackingError

CONFIG = Path("/etc/alfred-completion-v1/config.json")
INTAKE_CONFIG = Path("/home/alfred/Alfred/gateway/v1-1-intake.json")
PAUSE = Path("/home/alfred/Alfred/gateway/PAUSE")
MAX_BYTES = 1024 * 1024
CONNECT_TIMEOUT = 2
# Well inside the worker's own limit; a slower acknowledgement stays uncertain.
ACK_TIMEOUT = 30
BINDING_FIELDS = {
    "project",
    "task_id",
    "destination",
    "base_branch",
    "publication_branch",
    "final_revision",
}


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def protected_json(path: Path, *, trusted_uid=0, trusted_root=Path("/")):
    """Descriptor-pinned, bounded input from a non-writable protected path."""
    if (
        not path.is_absolute()
        or not path.is_relative_to(trusted_root)
        or ".." in path.parts
        or path == trusted_root
    ):
        raise ValueError("input outside protected root")
    fd = os.open(trusted_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        components = path.relative_to(trusted_root).parts
        for i, component in enumerate(components):
            parent = os.fstat(fd)
            if parent.st_uid != trusted_uid or parent.st_mode & 0o022:
                raise ValueError("unprotected input directory")
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if i != len(components) - 1:
                flags |= os.O_DIRECTORY
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != trusted_uid
            or info.st_mode & 0o022
            or info.st_nlink != 1
            or info.st_size > MAX_BYTES
        ):
            raise ValueError("unprotected input file")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("input exceeds size bound")
        value = json.loads(raw, object_pairs_hook=unique)
        if type(value) is not dict:
            raise ValueError("JSON object required")
        return value, hashlib.sha256(raw).hexdigest()
    finally:
        if fd != -1:
            os.close(fd)


def bundle(config_path=CONFIG, *, trusted_uid=0, trusted_root=Path("/")):
    config, _ = protected_json(
        config_path, trusted_uid=trusted_uid, trusted_root=trusted_root
    )
    if (
        config.get("schema") != "alfred.completion-config/1"
        or type(config.get("enabled")) is not bool
        or type(config.get("owner_merge_attested")) is not bool
        or set(config.get("binding", {})) != BINDING_FIELDS
        or re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", config["binding"].get("destination", "")
        )
        is None
        or type(config.get("owner_space_id")) is not str
        or not 1 <= len(config["owner_space_id"]) <= 200
        or type(config.get("owner_sender_id")) is not str
        or not config["owner_sender_id"]
        or re.fullmatch(r"[A-Za-z0-9-]{1,39}", config.get("owner_github_login", ""))
        is None
    ):
        raise ValueError("invalid protected completion configuration")
    values = {}
    # handoff.31: the Publisher's merge record, pinned like the others when present.
    names = ("publication-result", "publication-plan", "owner-authorization")
    if "merge-result-sha256" in config:
        names += ("merge-result",)
    for name in names:
        value, digest = protected_json(
            config_path.parent / (name + ".json"),
            trusted_uid=trusted_uid,
            trusted_root=trusted_root,
        )
        if digest != config.get(name + "-sha256"):
            raise ValueError("pinned publication input digest mismatch")
        values[name] = value
    return config, values


def github_pr(repository, number):
    # Uses the existing operator's gh credentials for one read-only endpoint.
    result = subprocess.run(
        [
            "/usr/bin/gh",
            "api",
            "--hostname",
            "github.com",
            "--method",
            "GET",
            f"repos/{repository}/pulls/{number}",
        ],
        capture_output=True,
        stdin=subprocess.DEVNULL,
        timeout=20,
        check=False,
    )
    if result.returncode or len(result.stdout) > MAX_BYTES:
        raise ValueError("GitHub reconciliation unavailable")
    return json.loads(result.stdout, object_pairs_hook=unique)


def not_paused(path=PAUSE):
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    return False


class PhotonSender:
    """Wrap the existing loopback /send contract; return its send receipt ID.

    This confirms SDK send acceptance, not end-to-end delivery or owner reading.
    There are no retries and no fallback routes.

    The sidecar answers only after Photon's remote send returns, so the message can
    reach the owner seconds before the acknowledgement. Connecting stays short (if it
    fails, nothing was sent); waiting for the acknowledgement does not. A two-second
    wait recorded demo-site T-0003's delivered text as uncertain.
    """

    def __init__(self, *, port, token, space_id, connection=http.client.HTTPConnection):
        if (
            type(port) is not int
            or not 1 <= port <= 65535
            or type(token) is not str
            or not token
            or "\n" in token
            or "\r" in token
        ):
            raise ValueError("invalid protected Photon transport")
        self.port, self.token, self.space_id, self.connection = (
            port,
            token,
            space_id,
            connection,
        )

    def __call__(self, notification):
        conn = self.connection("127.0.0.1", self.port, timeout=CONNECT_TIMEOUT)
        try:
            conn.connect()
            conn.sock.settimeout(ACK_TIMEOUT)
            body = json.dumps(
                {"spaceId": self.space_id, "text": notification.text, "format": "text"}
            ).encode()
            conn.request(
                "POST",
                "/send",
                body,
                {
                    "Content-Type": "application/json",
                    "x-hermes-sidecar-token": self.token,
                },
            )
            response = conn.getresponse()
            raw = response.read(1025)
            if response.status != 200 or len(raw) > 1024:
                raise ValueError("Photon acknowledgement unavailable")
            result = json.loads(raw, object_pairs_hook=unique)
            receipt = result.get("messageId")
            if (
                result.get("ok") is not True
                or type(receipt) is not str
                or not 1 <= len(receipt) <= 200
                or any(ord(c) < 33 for c in receipt)
            ):
                raise ValueError("Photon acknowledgement unavailable")
            return receipt
        finally:
            conn.close()


def photon_sender(config):
    # Same private Intake configuration and single existing Photon connection.
    fd = os.open(INTAKE_CONFIG, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_mode & 0o077
            or info.st_size > 4096
        ):
            raise ValueError("protected Intake transport configuration unavailable")
        transport = json.loads(stream.read(4097), object_pairs_hook=unique)
    if transport["owner_sender_id"] != config["owner_sender_id"]:
        raise ValueError("completion owner routing mismatch")
    return PhotonSender(
        port=transport["sidecar_port"],
        token=transport["sidecar_token"],
        space_id=config["owner_space_id"],
    )


def run(
    config_path=CONFIG,
    *,
    send=False,
    get_pr=github_pr,
    sender_factory=photon_sender,
    paused_check=not_paused,
    trusted_uid=0,
    trusted_root=Path("/"),
):
    config, values = bundle(
        config_path, trusted_uid=trusted_uid, trusted_root=trusted_root
    )
    if paused_check() is not True:
        raise ValueError("completion held by PAUSE")
    if send and config["enabled"] is not True:
        raise ValueError("completion sending is disabled")
    schema = json.loads(
        Path(__file__).with_name("publication-result.schema.json").read_bytes()
    )
    notification = prepare(
        result=values["publication-result"],
        plan=values["publication-plan"],
        authorization=values["owner-authorization"],
        binding=config["binding"],
        plan_digest=config["publication-plan-sha256"],
        result_schema=schema,
        get_pr=get_pr,
        owner_login=config["owner_github_login"],
        owner_merge_attested=config["owner_merge_attested"],
        merge=values.get("merge-result"),
    )
    if not send:
        return {"status": "PREVIEW", "text": notification.text}
    sender = sender_factory(config)

    def guarded_send(notice):
        if paused_check() is not True:
            raise ValueError("completion held by PAUSE")
        return sender(notice)

    status = DeliveryTracker(Path(config["state_directory"])).deliver(
        notification, guarded_send
    )
    return {"status": status, "confirmation": "Photon send acceptance only"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("preview", "initialize", "notify"))
    parser.add_argument("--config", type=Path, default=CONFIG)
    args = parser.parse_args(argv)
    try:
        if args.mode == "initialize":
            config, _ = bundle(args.config)
            DeliveryTracker(Path(config["state_directory"])).initialize()
            output = {"status": "INITIALIZED"}
        else:
            output = run(args.config, send=args.mode == "notify")
        print(json.dumps(output))
        return 2 if output["status"] == "uncertain" else 0
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        ValidationError,
        DeliveryTrackingError,
        subprocess.SubprocessError,
        http.client.HTTPException,
    ):
        # Input, transport and credential exception details are never printed.
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "detail": "completion prerequisites or reconciliation failed",
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
