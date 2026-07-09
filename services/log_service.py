from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


class ChatLogService:
    def __init__(self, log_path: Path, user_text_mode: str = "masked") -> None:
        self.log_path = log_path
        self.user_text_mode = user_text_mode if user_text_mode in {"raw", "masked", "off"} else "masked"

    def append_chat(
        self,
        user_text: str,
        assistant_text: str,
        intent: str,
        language: str,
        sources: Optional[List[dict]] = None,
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "assistant": assistant_text,
            "intent": intent,
            "language": language,
            "user_text_mode": self.user_text_mode,
        }
        user_value = self._prepare_user_text(user_text)
        if user_value is not None:
            entry["user"] = user_value
        if sources is not None:
            entry["sources"] = sources
        self._append(entry)

    def read(self, limit: int) -> List[dict]:
        bounded = max(1, min(limit, 1000))
        if not self.log_path.exists():
            return []
        entries: List[dict] = []
        try:
            with self.log_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []
        return entries[-bounded:]

    def _append(self, entry: dict) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except OSError:
            return

    def _prepare_user_text(self, user_text: str) -> Optional[str]:
        if self.user_text_mode == "off":
            return None
        if self.user_text_mode == "raw":
            return user_text
        return self._mask_user_text(user_text)

    @staticmethod
    def _mask_user_text(user_text: str) -> str:
        text = (user_text or "").strip()
        if not text:
            return ""

        replacements = [
            (r"\b[\w.\-+]+@[\w.\-]+\.\w+\b", "[redacted-email]"),
            (r"\b(?:\+?\d[\d\s().-]{7,}\d)\b", "[redacted-phone]"),
            (r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", "[redacted-date]"),
            (r"\b[A-Z0-9]{16,}\b", "[redacted-token]"),
            (r"\b\d{6,}\b", "[redacted-number]"),
        ]
        for pattern, replacement in replacements:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        if len(text) > 280:
            return text[:277] + "..."
        return text
