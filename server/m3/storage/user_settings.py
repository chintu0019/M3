"""
M3 User Settings Store -- persists runtime config changes to a JSON file.

Layering: config.yml defaults < user_settings.json overrides < env vars.
Changes made through the web UI are saved here so they survive restarts
without touching config.yml.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("m3.user_settings")

DEFAULT_PATH = Path("/data/user_settings.json")


class UserSettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_PATH
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
                logger.info(f"Loaded user settings from {self.path}")
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Failed to load user settings: {e}")
                self._data = {}
        else:
            self._data = {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, indent=2))
        except OSError as e:
            logger.error(f"Failed to save user settings: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> None:
        self._data.pop(key, None)
        self._save()

    # -- LLM provider helpers --

    def get_providers(self) -> dict[str, dict]:
        """Get user-configured providers."""
        return self.get("llm_providers", {})

    def set_provider(self, name: str, config: dict) -> None:
        """Add or update a provider."""
        providers = self.get_providers()
        providers[name] = config
        self.set("llm_providers", providers)

    def delete_provider(self, name: str) -> None:
        """Remove a provider."""
        providers = self.get_providers()
        providers.pop(name, None)
        self.set("llm_providers", providers)

    def get_active_provider(self) -> str | None:
        """Get the user's active provider choice."""
        return self.get("active_provider")

    def set_active_provider(self, name: str) -> None:
        self.set("active_provider", name)
