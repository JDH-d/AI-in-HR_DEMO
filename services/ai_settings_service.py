from __future__ import annotations

import json
from pathlib import Path

from core.files import atomic_write_json
from rag.prompts import DEFAULT_SYSTEM_PROMPT

AI_SETTINGS_DEFAULTS = {
    "strict_grounding": True,
    "concise_answers": True,
    "ask_clarifying_questions": True,
    "suggest_next_steps": True,
    "show_sources": True,
    "auto_index_uploads": True,
}


class AISettingsService:
    """Persists AI switches and the system prompt as one atomic configuration."""

    def __init__(self, path: Path, legacy_system_prompt_path: Path | None = None) -> None:
        self.path = path
        self.legacy_system_prompt_path = legacy_system_prompt_path

    def get(self) -> dict[str, bool]:
        return self._settings_from_payload(self._read_payload())

    def _settings_from_payload(self, payload: dict) -> dict[str, bool]:
        stored_settings = payload.get("settings", payload)
        if not isinstance(stored_settings, dict):
            stored_settings = {}
        return self._normalize_settings(stored_settings)

    def get_system_prompt(self) -> str:
        return self._system_prompt_from_payload(self._read_payload())

    def _system_prompt_from_payload(self, payload: dict) -> str:
        value = payload.get("system_prompt")
        if isinstance(value, str) and value.strip():
            return value.strip()
        if self.legacy_system_prompt_path is not None:
            try:
                legacy = self.legacy_system_prompt_path.read_text(encoding="utf-8").strip()
            except (FileNotFoundError, OSError):
                legacy = ""
            if legacy:
                return legacy
        return DEFAULT_SYSTEM_PROMPT

    def get_configuration(self) -> dict:
        payload = self._read_payload()
        return {
            "settings": self._settings_from_payload(payload),
            "system_prompt": self._system_prompt_from_payload(payload),
            "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        }

    def save_configuration(
        self,
        settings: dict[str, bool],
        system_prompt: str,
    ) -> dict:
        normalized_prompt = system_prompt.strip()
        if not normalized_prompt:
            raise ValueError("System prompt cannot be empty.")
        normalized_settings = self._normalize_settings(settings)
        self._write(normalized_settings, normalized_prompt)
        return {
            "settings": normalized_settings,
            "system_prompt": normalized_prompt,
            "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        }

    def _write(self, settings: dict[str, bool], system_prompt: str) -> None:
        atomic_write_json(
            self.path,
            {"settings": settings, "system_prompt": system_prompt},
            indent=2,
        )

    def _read_payload(self) -> dict:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _normalize_settings(settings: dict) -> dict[str, bool]:
        return {
            key: value if isinstance(value := settings.get(key), bool) else default
            for key, default in AI_SETTINGS_DEFAULTS.items()
        }
