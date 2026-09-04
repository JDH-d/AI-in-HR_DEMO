from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

logger = logging.getLogger(__name__)


class ChatLogService:
    def __init__(self, log_path: Path, user_text_mode: str = "masked") -> None:
        self.log_path = log_path
        if user_text_mode not in {"raw", "masked", "off"}:
            raise ValueError("user_text_mode must be raw, masked, or off")
        self.user_text_mode = user_text_mode
        self._lock = RLock()

    def append_chat(
        self,
        user_text: str,
        assistant_text: str,
        intent: str,
        language: str,
        sources: list[dict] | None = None,
        outcome_code: str = "unknown",
    ) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "assistant": assistant_text,
            "intent": intent,
            "language": language,
            "user_text_mode": self.user_text_mode,
            "outcome_code": outcome_code,
        }
        user_value = self._prepare_user_text(user_text)
        if user_value is not None:
            entry["user"] = user_value
        if sources is not None:
            entry["sources"] = sources
        self._append(entry)

    def read(self, limit: int | None = None) -> list[dict]:
        with self._lock:
            if not self.log_path.exists():
                return []
            entries: list[dict] = []
            try:
                with self.log_path.open("r", encoding="utf-8") as handle:
                    for line_number, line in enumerate(handle, start=1):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            logger.warning(
                                "Ignoring malformed chat log entry path=%s line=%s",
                                self.log_path,
                                line_number,
                            )
                            continue
            except OSError as exc:
                logger.warning("Unable to read chat log path=%s error=%s", self.log_path, exc)
                return []
        if limit is None:
            return entries
        bounded = max(1, min(limit, 10_000))
        return entries[-bounded:]

    def _append(self, entry: dict) -> None:
        with self._lock:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
            except OSError as exc:
                logger.warning("Unable to append chat log path=%s error=%s", self.log_path, exc)

    def _prepare_user_text(self, user_text: str) -> str | None:
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
