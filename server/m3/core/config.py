"""User config for M3 — ~/.config/m3/config.yml.

Intentionally small. Stores settings the user configures once and forgets:
- Telegram bot token + allowlist
- Server URL (if non-default)
- LLM provider choice + API key (future — not wired yet)

Security model: the file is chmod 600 at write time. For higher assurance,
users can put secrets in their OS keychain and point env vars at the values;
the config file's value is always the fallback.

Env vars always override config.yml. Order of precedence (highest first):
  1. Function argument (explicit)
  2. Environment variable
  3. config.yml
  4. Hard-coded default
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR_ENV = "M3_CONFIG_DIR"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / "m3"


def config_dir() -> Path:
    """Return the user config directory. Honors $M3_CONFIG_DIR for tests."""
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else DEFAULT_CONFIG_DIR


def config_path() -> Path:
    return config_dir() / "config.yml"


@dataclass
class TelegramConfig:
    token: str | None = None
    allowed_chats: list[int] = field(default_factory=list)
    server_url: str | None = None


@dataclass
class LLMConfig:
    provider: str | None = None         # "ollama" | "anthropic" | "local_agent" | None (= env-driven default)
    ollama_host: str | None = None
    ollama_model: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    # local_agent: shells out to a user-installed AI CLI (claude, codex,
    # gemini, aider, mods, llm, or a custom command). No M3-managed key --
    # auth is whatever the user already configured in that CLI.
    local_agent_command: str | None = None
    local_agent_args: list[str] | None = None


@dataclass
class AuthConfig:
    """Opt-in bearer-token auth for /api/v1/*.

    Off by default: M3 binds 127.0.0.1 and the loopback is the security
    boundary. Turn it on when exposing the server beyond localhost (e.g.
    reaching it over Tailscale from a phone).
    """
    require_auth: bool = False
    api_key: str | None = None


@dataclass
class M3Config:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "telegram": {
                "token": self.telegram.token,
                "allowed_chats": list(self.telegram.allowed_chats),
                "server_url": self.telegram.server_url,
            },
            "llm": {
                "provider": self.llm.provider,
                "ollama_host": self.llm.ollama_host,
                "ollama_model": self.llm.ollama_model,
                "anthropic_api_key": self.llm.anthropic_api_key,
                "anthropic_model": self.llm.anthropic_model,
                "local_agent_command": self.llm.local_agent_command,
                "local_agent_args": (
                    list(self.llm.local_agent_args)
                    if self.llm.local_agent_args is not None
                    else None
                ),
            },
            "auth": {
                "require_auth": self.auth.require_auth,
                "api_key": self.auth.api_key,
            },
        }


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _str_list_or_none(value: Any) -> list[str] | None:
    """Coerce a YAML list-of-strings to ``list[str]``; None on anything else.

    Used for ``local_agent_args`` so a malformed YAML entry doesn't crash
    config load -- worst case the args fall back to defaults at runtime.
    """
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            out.append(item)
    return out


def load() -> M3Config:
    """Read config.yml. Returns a blank M3Config if the file doesn't exist."""
    path = config_path()
    if not path.exists():
        return M3Config()
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError:
        # Don't crash on malformed config — behave as if absent.
        return M3Config()
    if not isinstance(raw, dict):
        return M3Config()
    tg = raw.get("telegram") or {}
    if not isinstance(tg, dict):
        tg = {}
    allowed = tg.get("allowed_chats") or []
    # Coerce each allowlist entry to int; skip anything that doesn't parse.
    allowed_ints: list[int] = []
    for v in allowed:
        try:
            allowed_ints.append(int(v))
        except (TypeError, ValueError):
            continue
    llm_raw = raw.get("llm") or {}
    if not isinstance(llm_raw, dict):
        llm_raw = {}
    auth_raw = raw.get("auth") or {}
    if not isinstance(auth_raw, dict):
        auth_raw = {}
    return M3Config(
        telegram=TelegramConfig(
            token=_str_or_none(tg.get("token")),
            allowed_chats=allowed_ints,
            server_url=_str_or_none(tg.get("server_url")),
        ),
        llm=LLMConfig(
            provider=_str_or_none(llm_raw.get("provider")),
            ollama_host=_str_or_none(llm_raw.get("ollama_host")),
            ollama_model=_str_or_none(llm_raw.get("ollama_model")),
            anthropic_api_key=_str_or_none(llm_raw.get("anthropic_api_key")),
            anthropic_model=_str_or_none(llm_raw.get("anthropic_model")),
            local_agent_command=_str_or_none(llm_raw.get("local_agent_command")),
            local_agent_args=_str_list_or_none(llm_raw.get("local_agent_args")),
        ),
        auth=AuthConfig(
            require_auth=bool(auth_raw.get("require_auth", False)),
            api_key=_str_or_none(auth_raw.get("api_key")),
        ),
    )


def save(cfg: M3Config) -> Path:
    """Atomic-ish write of config.yml with mode 600. Creates the dir if missing."""
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = config_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(cfg.to_dict(), sort_keys=True))
    try:
        tmp.chmod(0o600)
    except OSError:
        pass   # best effort on filesystems that don't support POSIX modes
    tmp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def update(mutator) -> M3Config:
    """Load, mutate, save. `mutator` receives the M3Config and can change it in place
    OR return a new one."""
    cfg = load()
    result = mutator(cfg)
    if isinstance(result, M3Config):
        cfg = result
    save(cfg)
    return cfg


# --- resolution helpers: env > config.yml > default ---


def telegram_token() -> str | None:
    return os.environ.get("M3_TELEGRAM_TOKEN") or load().telegram.token


def telegram_allowed_chats() -> frozenset[int]:
    env = os.environ.get("M3_TELEGRAM_ALLOWED_CHATS")
    if env:
        out: set[int] = set()
        for piece in env.split(","):
            piece = piece.strip()
            if piece:
                try:
                    out.add(int(piece))
                except ValueError:
                    continue
        return frozenset(out)
    return frozenset(load().telegram.allowed_chats)


def telegram_server_url() -> str:
    return (
        os.environ.get("M3_SERVER_URL")
        or load().telegram.server_url
        or "http://127.0.0.1:7007"
    )


def llm_provider() -> str:
    return os.environ.get("M3_LLM_PROVIDER") or load().llm.provider or "ollama"


def ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST") or load().llm.ollama_host or "http://localhost:11434"


def ollama_model() -> str:
    return os.environ.get("OLLAMA_MODEL") or load().llm.ollama_model or "qwen2.5:7b"


def anthropic_api_key() -> str | None:
    return os.environ.get("ANTHROPIC_API_KEY") or load().llm.anthropic_api_key or None


def anthropic_model() -> str:
    return (
        os.environ.get("ANTHROPIC_MODEL")
        or load().llm.anthropic_model
        or "claude-sonnet-4-20250514"
    )


def local_agent_command() -> str:
    """The CLI binary to invoke for the local_agent provider.

    Resolution order: ``LOCAL_AGENT_COMMAND`` env > config.yml > ``"claude"``.
    The default matches Claude Code, the most common installed agent.
    """
    return (
        os.environ.get("LOCAL_AGENT_COMMAND")
        or load().llm.local_agent_command
        or "claude"
    )


def local_agent_args() -> list[str]:
    """Args passed to the local_agent CLI before its prompt is piped on stdin.

    Resolution order: ``LOCAL_AGENT_ARGS`` env (comma-separated) > config.yml >
    ``["-p"]``. The default is Claude Code's non-interactive flag and works
    for most CLIs in our KNOWN_AGENTS table.
    """
    env = os.environ.get("LOCAL_AGENT_ARGS")
    if env is not None:
        # Comma-separated so a single env var can carry a multi-token list
        # without shell quoting drama. Empty entries are dropped.
        return [piece.strip() for piece in env.split(",") if piece.strip()]
    cfg = load().llm.local_agent_args
    # ``cfg is None`` means "user never set it" -> fall back to the default.
    # An explicit empty list ``[]`` means "no args" -- needed for CLIs like
    # ``mods`` or ``llm`` that take the prompt directly without flags.
    return list(cfg) if cfg is not None else ["-p"]


def auth_required() -> bool:
    """True when the HTTP surface should enforce bearer-token auth."""
    env = os.environ.get("M3_REQUIRE_AUTH")
    if env is not None:
        return env.lower() in ("1", "true", "yes")
    return load().auth.require_auth


def auth_api_key() -> str | None:
    """The configured API key (env > config.yml), or None."""
    return os.environ.get("M3_API_KEY") or load().auth.api_key
