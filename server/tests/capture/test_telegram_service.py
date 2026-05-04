"""Tests for the service installer. Platform-specific pieces (launchctl,
systemctl) are mocked — we only verify file contents and that the right
commands are invoked."""

from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

import pytest

from m3.capture import telegram_service as svc


@pytest.fixture
def home_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    # On macOS systems some modules cache Path.home() — patch it defensively.
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


@pytest.fixture
def fake_m3_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    fake = tmp_path / "m3"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setattr(svc.shutil, "which", lambda name: str(fake) if name == "m3" else None)
    return str(fake)


@pytest.fixture
def _suppress_subprocess(monkeypatch: pytest.MonkeyPatch):
    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_m3_binary_missing_raises(monkeypatch):
    monkeypatch.setattr(svc.shutil, "which", lambda name: None)
    with pytest.raises(svc.ServiceError, match="not on PATH"):
        svc._m3_binary()


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS launchd test")
def test_mac_install_writes_plists(home_override, fake_m3_binary, _suppress_subprocess):
    paths = svc._mac_install()
    assert len(paths) == 2
    for p in paths:
        assert p.exists()
        content = p.read_text()
        assert "<plist" in content and "</plist>" in content
        assert fake_m3_binary in content
    # Expect ~/Library/LaunchAgents/ location
    for p in paths:
        assert "LaunchAgents" in str(p)
    # Should have invoked `launchctl bootstrap` (or fallback `launchctl load`)
    assert any(cmd[0] == "launchctl" for cmd in _suppress_subprocess)


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS launchd test")
def test_mac_uninstall_removes_plists(home_override, fake_m3_binary, _suppress_subprocess):
    svc._mac_install()
    removed = svc._mac_uninstall()
    assert len(removed) == 2
    for p in removed:
        assert not p.exists()


def test_systemd_install_writes_units(home_override, fake_m3_binary, _suppress_subprocess, monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    paths = svc._systemd_install()
    assert len(paths) == 2
    for p in paths:
        assert p.exists()
        content = p.read_text()
        assert "[Unit]" in content and "[Service]" in content and "[Install]" in content
        assert fake_m3_binary in content
    # Dependency ordering: m3-telegram.service should reference m3-server.service
    tg = next(p for p in paths if p.name == "m3-telegram.service")
    assert "m3-server.service" in tg.read_text()
    # Systemctl got called with --user
    assert any(cmd[:3] == ["systemctl", "--user", "daemon-reload"] for cmd in _suppress_subprocess)


def test_install_on_unsupported_platform_raises(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    with pytest.raises(svc.ServiceError, match="not supported"):
        svc.install()
