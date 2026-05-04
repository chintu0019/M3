"""Install `m3 telegram` as a background service that starts on login.

macOS: writes a user LaunchAgent to ~/Library/LaunchAgents/local.m3.telegram.plist
       and loads it via `launchctl bootstrap gui/$UID`.

Linux: writes a systemd user unit to ~/.config/systemd/user/m3-telegram.service
       and enables it via `systemctl --user enable --now`.

Both paths also include an accompanying `m3 start` service (local.m3.server /
m3-server.service) so the bot always has the HTTP API to talk to. They run as
the current user, no sudo needed.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


SERVER_LABEL = "local.m3.server"
TELEGRAM_LABEL = "local.m3.telegram"


class ServiceError(Exception):
    pass


def _m3_binary() -> str:
    found = shutil.which("m3")
    if not found:
        raise ServiceError(
            "`m3` binary not on PATH. Install first (e.g. `pipx install m3`) and re-run."
        )
    return found


# --- macOS launchctl ---


def _mac_launch_agents_dir() -> Path:
    d = Path.home() / "Library" / "LaunchAgents"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mac_plist(label: str, program_args: list[str], *, out_log: Path, err_log: Path) -> str:
    args_xml = "\n".join(f"        <string>{a}</string>" for a in program_args)
    env_xml = ""
    path_env = os.environ.get("PATH", "")
    if path_env:
        env_xml = f"""
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{path_env}</string>
    </dict>"""
    return dedent(f"""\
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
                "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>Label</key>
            <string>{label}</string>
            <key>ProgramArguments</key>
            <array>
        {args_xml}
            </array>
            <key>RunAtLoad</key>
            <true/>
            <key>KeepAlive</key>
            <true/>{env_xml}
            <key>StandardOutPath</key>
            <string>{out_log}</string>
            <key>StandardErrorPath</key>
            <string>{err_log}</string>
        </dict>
        </plist>
        """)


def _mac_install() -> list[Path]:
    m3 = _m3_binary()
    log_dir = Path.home() / "Library" / "Logs" / "M3"
    log_dir.mkdir(parents=True, exist_ok=True)
    la = _mac_launch_agents_dir()

    server_plist = la / f"{SERVER_LABEL}.plist"
    telegram_plist = la / f"{TELEGRAM_LABEL}.plist"

    server_plist.write_text(_mac_plist(
        label=SERVER_LABEL,
        program_args=[m3, "start"],
        out_log=log_dir / "server.out.log",
        err_log=log_dir / "server.err.log",
    ))
    telegram_plist.write_text(_mac_plist(
        label=TELEGRAM_LABEL,
        program_args=[m3, "telegram"],
        out_log=log_dir / "telegram.out.log",
        err_log=log_dir / "telegram.err.log",
    ))

    uid = os.getuid()
    domain = f"gui/{uid}"
    # `launchctl bootstrap` is the modern way; `load` is legacy but widely available.
    for plist in (server_plist, telegram_plist):
        _run(["launchctl", "bootout", domain, str(plist)], check=False)
        r = subprocess.run(["launchctl", "bootstrap", domain, str(plist)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            # Fall back to the legacy `load -w` path.
            _run(["launchctl", "load", "-w", str(plist)])
    return [server_plist, telegram_plist]


def _mac_uninstall() -> list[Path]:
    la = _mac_launch_agents_dir()
    uid = os.getuid()
    domain = f"gui/{uid}"
    removed: list[Path] = []
    for label in (TELEGRAM_LABEL, SERVER_LABEL):
        plist = la / f"{label}.plist"
        if plist.exists():
            _run(["launchctl", "bootout", domain, str(plist)], check=False)
            _run(["launchctl", "unload", str(plist)], check=False)
            plist.unlink()
            removed.append(plist)
    return removed


# --- Linux systemd user unit ---


def _systemd_user_dir() -> Path:
    d = Path.home() / ".config" / "systemd" / "user"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _systemd_install() -> list[Path]:
    m3 = _m3_binary()
    sd = _systemd_user_dir()
    log_dir = Path.home() / ".local" / "state" / "m3"
    log_dir.mkdir(parents=True, exist_ok=True)

    server_unit = sd / "m3-server.service"
    telegram_unit = sd / "m3-telegram.service"

    server_unit.write_text(dedent(f"""\
        [Unit]
        Description=M3 local server
        After=network.target

        [Service]
        Type=simple
        ExecStart={m3} start
        Restart=on-failure
        RestartSec=2
        StandardOutput=append:{log_dir}/server.log
        StandardError=append:{log_dir}/server.err.log

        [Install]
        WantedBy=default.target
        """))

    telegram_unit.write_text(dedent(f"""\
        [Unit]
        Description=M3 Telegram capture bot
        After=m3-server.service
        Wants=m3-server.service

        [Service]
        Type=simple
        ExecStart={m3} telegram
        Restart=on-failure
        RestartSec=2
        StandardOutput=append:{log_dir}/telegram.log
        StandardError=append:{log_dir}/telegram.err.log

        [Install]
        WantedBy=default.target
        """))

    _run(["systemctl", "--user", "daemon-reload"])
    _run(["systemctl", "--user", "enable", "--now", "m3-server.service"])
    _run(["systemctl", "--user", "enable", "--now", "m3-telegram.service"])
    return [server_unit, telegram_unit]


def _systemd_uninstall() -> list[Path]:
    sd = _systemd_user_dir()
    removed: list[Path] = []
    for name in ("m3-telegram.service", "m3-server.service"):
        unit = sd / name
        if unit.exists():
            _run(["systemctl", "--user", "disable", "--now", name], check=False)
            unit.unlink()
            removed.append(unit)
    _run(["systemctl", "--user", "daemon-reload"], check=False)
    return removed


# --- public API ---


def install() -> list[Path]:
    system = platform.system()
    if system == "Darwin":
        return _mac_install()
    if system == "Linux":
        return _systemd_install()
    raise ServiceError(f"Service install not supported on {system!r}. Run `m3 start` + `m3 telegram` manually.")


def uninstall() -> list[Path]:
    system = platform.system()
    if system == "Darwin":
        return _mac_uninstall()
    if system == "Linux":
        return _systemd_uninstall()
    raise ServiceError(f"Service uninstall not supported on {system!r}.")


def _run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise ServiceError(f"command failed: {' '.join(cmd)}\n  stdout: {r.stdout.strip()}\n  stderr: {r.stderr.strip()}")
    return r
