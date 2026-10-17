from pathlib import Path


def test_current_photon_sidecar_has_unrestricted_attachment_path_characterization():
    """Records the current interface risk; this is not an acceptance test."""
    source = Path("/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/sidecar/index.mjs").read_text()
    adapter = Path("/home/alfred/.hermes/hermes-agent/plugins/platforms/photon/adapter.py").read_text()
    assert 'req.url === "/send-attachment"' in source
    assert 'typeof path !== "string"' in source
    assert "attachment(path," in source and "voice(path," in source
    assert '"X-Hermes-Sidecar-Token": self._sidecar_token' in adapter
