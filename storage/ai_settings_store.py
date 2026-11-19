from __future__ import annotations

from pathlib import Path

from storage.json_store import read_json, write_json

AI_SETTINGS_DEFAULTS = {
    "strict_grounding": True,
    "concise_answers": True,
    "ask_clarifying_questions": True,
    "suggest_next_steps": True,
    "show_sources": True,
    "auto_index_uploads": True,
}


class AISettingsStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self) -> dict[str, bool]:
        return self._normalize(read_json(self.path, {}))

    def save(self, settings: dict[str, bool]) -> dict[str, bool]:
        normalized = self._normalize(settings)
        write_json(self.path, normalized)
        return normalized

    @staticmethod
    def _normalize(payload: object) -> dict[str, bool]:
        if not isinstance(payload, dict):
            return dict(AI_SETTINGS_DEFAULTS)
        return {
            key: value if isinstance(value := payload.get(key), bool) else default
            for key, default in AI_SETTINGS_DEFAULTS.items()
        }
