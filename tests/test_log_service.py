from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from services.log_service import ChatLogService


class ChatLogServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "chat.jsonl"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_concurrent_appends_remain_complete_json_lines(self) -> None:
        service = ChatLogService(self.path, user_text_mode="raw")

        def append(index: int) -> None:
            service.append_chat(
                f"Question {index}",
                f"Answer {index}",
                "work",
                "en",
                outcome_code="grounded",
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(append, range(100)))

        entries = service.read()
        self.assertEqual(len(entries), 100)
        self.assertEqual(
            {entry["user"] for entry in entries}, {f"Question {i}" for i in range(100)}
        )

    def test_masked_mode_redacts_common_personal_values(self) -> None:
        service = ChatLogService(self.path, user_text_mode="masked")
        service.append_chat(
            "Email me@example.com or call +1 212 555 0199 on 04/10/2030",
            "Recorded.",
            "work",
            "en",
        )

        user_text = service.read()[0]["user"]
        self.assertIn("[redacted-email]", user_text)
        self.assertIn("[redacted-phone]", user_text)
        self.assertIn("[redacted-date]", user_text)

    def test_read_ignores_a_malformed_line_and_applies_limit(self) -> None:
        self.path.write_text('{"id": 1}\nnot-json\n{"id": 2}\n', encoding="utf-8")
        service = ChatLogService(self.path)

        self.assertEqual(service.read(limit=1), [{"id": 2}])


if __name__ == "__main__":
    unittest.main()
