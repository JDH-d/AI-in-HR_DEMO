from __future__ import annotations

import json
from pathlib import Path

AI_SETTINGS_DEFAULTS = {
    "strict_grounding": True,
    "concise_answers": True,
    "ask_clarifying_questions": True,
    "suggest_next_steps": True,
    "show_sources": True,
    "auto_index_uploads": True,
}


class AISettingsService:
    def __init__(self, path: Path) -> None:
        self.path = path

    def get(self) -> dict[str, bool]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return dict(AI_SETTINGS_DEFAULTS)
        if not isinstance(payload, dict):
            return dict(AI_SETTINGS_DEFAULTS)
        return {
            key: value if isinstance(value := payload.get(key), bool) else default
            for key, default in AI_SETTINGS_DEFAULTS.items()
        }

    def save(self, settings: dict[str, bool]) -> dict[str, bool]:
        normalized = {
            key: value if isinstance(value := settings.get(key), bool) else default
            for key, default in AI_SETTINGS_DEFAULTS.items()
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(normalized, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
        return normalized
