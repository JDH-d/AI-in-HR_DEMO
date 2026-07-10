import json
import shutil
import unittest
from pathlib import Path

from services.ai_settings_service import AI_SETTINGS_DEFAULTS, AISettingsService


class AISettingsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_tests" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.service = AISettingsService(self.temp_dir / "ai_settings.json")

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_or_invalid_file_uses_safe_defaults(self) -> None:
        self.assertEqual(self.service.get(), AI_SETTINGS_DEFAULTS)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.service.path.write_text("not-json", encoding="utf-8")
        self.assertEqual(self.service.get(), AI_SETTINGS_DEFAULTS)

    def test_save_normalizes_and_persists_only_supported_switches(self) -> None:
        saved = self.service.save(
            {
                "strict_grounding": False,
                "concise_answers": False,
                "unknown_setting": True,
            }
        )

        self.assertFalse(saved["strict_grounding"])
        self.assertFalse(saved["concise_answers"])
        self.assertTrue(saved["show_sources"])
        self.assertNotIn("unknown_setting", saved)
        self.assertEqual(json.loads(self.service.path.read_text(encoding="utf-8")), saved)


if __name__ == "__main__":
    unittest.main()
