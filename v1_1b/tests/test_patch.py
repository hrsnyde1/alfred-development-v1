"""The proposed Hermes patch must apply only in a disposable checkout."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINNED = Path("/home/alfred/.hermes/hermes-agent")
PINNED_REVISION = "26610b09a5c4aead8d8dfb276ea33decf0d7fa46"
PAIRS = {
    "gateway/session_context.py": "staging/hermes/gateway/session_context.py",
    "gateway/run.py": "staging/hermes/gateway/run.py",
    "gateway/run_turn.py": "staging/hermes/gateway/run_turn.py",
    "plugins/platforms/photon/adapter.py": "staging/adapter/adapter.py",
    "plugins/platforms/photon/sidecar/index.mjs": "staging/sidecar/index.mjs",
    "plugins/platforms/photon/sidecar/development-observe.mjs": "staging/sidecar/development-observe.mjs",
    "plugins/platforms/photon/sidecar/restricted-media.mjs": "staging/sidecar/restricted-media.mjs",
}


def test_patch_dry_run_and_byte_exact_apply(tmp_path):
    assert subprocess.check_output(["git", "-C", str(PINNED), "rev-parse", "HEAD"],
                                   text=True).strip() == PINNED_REVISION
    for target in PAIRS:
        destination = tmp_path / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = subprocess.run(["git", "-C", str(PINNED), "show",
                                 f"{PINNED_REVISION}:{target}"], capture_output=True)
        if source.returncode == 0:
            destination.write_bytes(source.stdout)
    patch = ROOT / "patches" / "hermes-photon-gateway-intake.proposed.patch"
    for mode in ("--dry-run", "--forward"):
        result = subprocess.run(["patch", "-d", str(tmp_path), "-p1", mode, "-i", str(patch)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
    for target, staged in PAIRS.items():
        assert (tmp_path / target).read_bytes() == (ROOT / staged).read_bytes()
