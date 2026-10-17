"""Unchanged Photon dependency ownership gate: pinned defect and corrected contract."""

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from development_challenge import install_patch as corrected
from development_challenge import phase_a_continue as preparation
from fresh_v1 import upgrade

LAB = Path(__file__).resolve().parents[1]
INSTALLER = (
    LAB
    / "dist/alfred-fresh-v1-1.0.1-development-handoff.1/development_challenge/install_patch.py"
)
PIN = "cee25c92548ae07bf3c68a25cb0fea00f2ff54ecbe94421e80368cfa4962629f"
ALFRED = 1000
INDEX = corrected.PHOTON + "index.mjs"


@pytest.mark.parametrize("owner,accepted", [(1000, False), (0, True)])
def test_pinned_root_installer_rejects_alfred_owned_dependency_even_with_correct_hash(
    tmp_path, monkeypatch, owner, accepted
):
    assert hashlib.sha256(INSTALLER.read_bytes()).hexdigest() == PIN
    spec = importlib.util.spec_from_file_location(
        "pinned_handoff_owner_gate", INSTALLER
    )
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    path = tmp_path / "index.mjs"
    path.write_bytes(b"unchanged disposable Photon dependency fixture\n")
    path.chmod(0o644)
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    lstat = Path.lstat

    def metadata(p, *args, **kwargs):
        result = lstat(p, *args, **kwargs)
        if p == path:
            fields = list(result)
            fields[4] = owner
            return os.stat_result(fields)
        return result

    # Model only caller/owner metadata; no real chown, sudo or host mutation.
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(Path, "lstat", metadata)
    before = path.read_bytes()
    if accepted:
        assert installer.checked(path, expected)[1] == before
    else:
        with pytest.raises(ValueError, match="installed contract mismatch"):
            installer.checked(path, expected)
    assert path.read_bytes() == before


# --- Corrected expected-owner contract (development-handoff.2) ------------------


def model_owners(monkeypatch, owners, *, alfred=ALFRED, euid=0):
    """Report modeled st_uid for chosen paths; never chown or touch real metadata."""
    lstat = Path.lstat

    def metadata(p, *args, **kwargs):
        result = lstat(p, *args, **kwargs)
        if p in owners:
            fields = list(result)
            fields[4] = owners[p]
            return os.stat_result(fields)
        return result

    monkeypatch.setattr(Path, "lstat", metadata)
    monkeypatch.setattr(corrected.os, "geteuid", lambda: euid)
    monkeypatch.setattr(
        corrected.pwd,
        "getpwnam",
        lambda name: SimpleNamespace(pw_uid={"alfred": alfred}[name]),
    )


def dependency(tmp_path, mode=0o644):
    path = tmp_path / "index.mjs"
    path.write_bytes(b"unchanged disposable Photon dependency fixture\n")
    path.chmod(mode)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def test_exception_names_only_the_unchanged_photon_index():
    assert corrected.DEPENDENCY_OWNERS == {INDEX: "alfred"}
    assert INDEX in corrected.DEPENDENCIES
    assert INDEX not in corrected.DESTINATIONS
    assert INDEX not in corrected.BASE
    assert preparation.DEPENDENCY_OWNERS == corrected.DEPENDENCY_OWNERS


@pytest.mark.parametrize(
    "owner,accepted", [(ALFRED, True), (0, False), (1001, False), (65534, False)]
)
def test_root_installer_requires_exact_alfred_owner_for_photon_index(
    tmp_path, monkeypatch, owner, accepted
):
    path, expected = dependency(tmp_path)
    model_owners(monkeypatch, {path: owner})
    before = path.read_bytes()
    uid = corrected.dependency_uid(INDEX)
    assert uid == ALFRED
    if accepted:
        assert corrected.checked(path, expected, uid)[1] == before
    else:
        with pytest.raises(ValueError, match="installed contract mismatch"):
            corrected.checked(path, expected, uid)
    assert path.read_bytes() == before


@pytest.mark.parametrize("name", sorted(set(corrected.DEPENDENCIES) - {INDEX}))
def test_every_other_dependency_still_requires_root_owner(tmp_path, monkeypatch, name):
    path, expected = dependency(tmp_path)
    model_owners(monkeypatch, {path: ALFRED})
    assert corrected.dependency_uid(name) == 0
    with pytest.raises(ValueError, match="installed contract mismatch"):
        corrected.checked(path, expected, corrected.dependency_uid(name))


@pytest.mark.parametrize("bad", ["digest", "group_write", "other_write", "hardlink"])
def test_alfred_owned_index_keeps_digest_mode_and_link_checks(
    tmp_path, monkeypatch, bad
):
    mode = {"group_write": 0o664, "other_write": 0o646}.get(bad, 0o644)
    path, expected = dependency(tmp_path, mode)
    if bad == "digest":
        expected = "0" * 64
    elif bad == "hardlink":
        os.link(path, tmp_path / "second-link")
    model_owners(monkeypatch, {path: ALFRED})
    with pytest.raises(ValueError, match="installed contract mismatch"):
        corrected.checked(path, expected, corrected.dependency_uid(INDEX))


def test_owner_exception_refuses_an_alfred_account_that_maps_to_root(monkeypatch):
    model_owners(monkeypatch, {}, alfred=0)
    with pytest.raises(ValueError, match="unprivileged"):
        corrected.dependency_uid(INDEX)


@pytest.fixture
def transaction_fixture(tmp_path, monkeypatch):
    """The real install transaction on a disposable root with a synthetic index."""
    from test_development_handoff_upgrade import original, write

    root, release = tmp_path / "host", tmp_path / "release"
    root.mkdir(mode=0o700)
    (root / ".fresh-v1-disposable-fixture").write_bytes(b"DISPOSABLE_V1_FIXTURE\n")
    index = b"synthetic unchanged Photon index fixture\n"
    monkeypatch.setitem(
        corrected.DEPENDENCIES, INDEX, hashlib.sha256(index).hexdigest()
    )
    for name, sha in {**corrected.BASE, **corrected.DEPENDENCIES}.items():
        write(
            upgrade.target(root, name), index if name == INDEX else original(name, sha)
        )
    manifest = original(
        corrected.DEVELOPER + "developer_v1/release.sha256",
        corrected.BASE[corrected.DEVELOPER + "developer_v1/release.sha256"],
    )
    for name, sha in corrected.inventory(manifest).items():
        write(
            upgrade.target(root, corrected.DEVELOPER + name),
            original(corrected.DEVELOPER + name, sha),
        )
    for name in set(corrected.DESTINATIONS.values()):
        write(release / name, (LAB / name).read_bytes())
    raw = "".join(
        hashlib.sha256((release / n).read_bytes()).hexdigest() + "  " + n + "\n"
        for n in sorted(set(corrected.DESTINATIONS.values()))
    ).encode()
    write(release / "MANIFEST.sha256", raw)
    for name in (upgrade.MARKER, "/home/alfred/Alfred/gateway/PAUSE"):
        write(upgrade.target(root, name), b"PRESERVE ORIGINAL FIXTURE\n")
    return root, release, upgrade.digest(raw), tmp_path / "backup"


# upgrade.validate_root accepts disposable roots only below a literal /tmp.
linux_tmp = pytest.mark.skipif(
    sys.platform != "linux", reason="disposable install roots require Linux /tmp"
)


def files(root):
    return {
        str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mode)
        for p in root.rglob("*")
        if p.is_file()
    }


@linux_tmp
def test_transaction_installs_with_alfred_owned_index_and_never_touches_it(
    transaction_fixture, monkeypatch
):
    root, release, pin, backup = transaction_fixture
    index = upgrade.target(root, INDEX)
    euid = os.geteuid()
    # Installer identity owns everything else; the index is modeled as alfred's.
    model_owners(monkeypatch, {index: euid + 1}, alfred=euid + 1, euid=euid)
    before = files(root)
    assert corrected.install(release, pin, root, backup)["status"] == "INSTALLED_HELD"
    after = files(root)
    key = str(index.relative_to(root))
    assert after[key] == before[key]
    assert {n for n in before if before[n] != after[n]} <= {
        n.lstrip("/") for n in corrected.DESTINATIONS
    }
    assert corrected.rollback(root, backup)["status"] == "ROLLED_BACK_HELD"
    assert files(root) == before


@linux_tmp
def test_transaction_refuses_installer_owned_index_before_any_write(
    transaction_fixture, monkeypatch
):
    root, release, pin, backup = transaction_fixture
    euid = os.geteuid()
    # The index is now owned by the installer identity, not the expected alfred.
    model_owners(monkeypatch, {}, alfred=euid + 1, euid=euid)
    before = files(root)
    with pytest.raises(ValueError, match="installed contract mismatch.*index.mjs"):
        corrected.install(release, pin, root, backup)
    assert files(root) == before and not backup.exists()


@pytest.fixture
def installed_fixture(tmp_path, monkeypatch):
    """Phase A installed-runtime check on disposable bytes and modeled owners."""
    monkeypatch.setattr(preparation, "ROOT", tmp_path)
    release = tmp_path / "release"
    pins = {}
    names = json.loads(
        (LAB / "development_challenge/installed-sha256.json").read_bytes()
    )
    for i, name in enumerate(names):
        raw = f"installed fixture {i}\n".encode()
        path = preparation.host(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        path.chmod(0o644)
        pins[name] = hashlib.sha256(raw).hexdigest()
    lines = []
    for i in range(29):
        name = f"developer_v1/fixture_{i}.py"
        raw = f"developer fixture {i}\n".encode()
        path = preparation.host("/opt/alfred-developer-v1/" + name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        # Explicit modes: the host's alfred umask (002) would otherwise make these
        # group-writable, which read() correctly refuses. Production files are 0644/0600.
        path.chmod(0o644)
        lines.append(hashlib.sha256(raw).hexdigest() + "  " + name)
    manifest = preparation.host("/opt/alfred-developer-v1/developer_v1/release.sha256")
    manifest.write_text("\n".join(lines) + "\n")
    manifest.chmod(0o644)
    pins["/opt/alfred-developer-v1/developer_v1/release.sha256"] = hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()
    pin_file = release / "development_challenge/installed-sha256.json"
    pin_file.parent.mkdir(parents=True)
    pin_file.write_text(json.dumps(pins))
    pin_file.chmod(0o600)
    marker = preparation.host("/opt/alfred-developer-v1/active")
    marker.write_bytes(b"ACTIVE FIXTURE\n")
    marker.chmod(0o644)
    policy = preparation.host("/etc/alfred-fresh-v1/policy.json")
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "enabled": True,
                "project": "dev-v1-accept",
                "destination": "hrsnyde1/alfred-dev-v1-acceptance",
            }
        )
    )
    policy.chmod(0o600)
    euid = os.geteuid()
    monkeypatch.setattr(
        preparation.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=euid + 1)
    )

    def owners(mapping):
        inodes = {preparation.host(n).stat().st_ino: uid for n, uid in mapping.items()}
        fstat = os.fstat

        def modeled(fd):
            result = fstat(fd)
            if result.st_ino in inodes:
                fields = list(result)
                fields[4] = inodes[result.st_ino]
                return os.stat_result(fields)
            return result

        monkeypatch.setattr(preparation.os, "fstat", modeled)

    return release, euid, owners


def test_phase_a_accepts_alfred_owned_photon_index(installed_fixture):
    release, euid, owners = installed_fixture
    owners({INDEX: euid + 1})
    preparation.installed(release)


def test_phase_a_rejects_installer_owned_photon_index(installed_fixture):
    release, _, _ = installed_fixture
    with pytest.raises(preparation.Blocked, match="ownership: .*index.mjs"):
        preparation.installed(release)


def test_phase_a_rejects_alfred_owner_anywhere_else(installed_fixture):
    release, euid, owners = installed_fixture
    other = corrected.PHOTON + "development-observe.mjs"
    owners({INDEX: euid + 1, other: euid + 1})
    with pytest.raises(preparation.Blocked, match="ownership: .*development-observe"):
        preparation.installed(release)


def test_phase_a_refuses_an_alfred_account_that_maps_to_root(
    installed_fixture, monkeypatch
):
    release, _, _ = installed_fixture
    monkeypatch.setattr(
        preparation.pwd, "getpwnam", lambda _: SimpleNamespace(pw_uid=0)
    )
    with pytest.raises(preparation.Blocked, match="privileged"):
        preparation.installed(release)


def test_prepare_script_applies_the_same_single_owner_exception():
    script = (LAB / "development_challenge/PHASE_A_PREPARE.sh").read_text()
    assert script.count("pwd.getpwnam('alfred').pw_uid") == 1
    assert "s.st_uid==owners.get(name,0)" in script
    assert INDEX in script
    # Developer inventory, activation marker and policy keep unconditional root checks.
    assert script.count("s.st_uid==0") == 3
