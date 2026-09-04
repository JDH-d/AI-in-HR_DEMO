import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_save_configuration_normalizes_and_persists_supported_switches(self) -> None:
        configuration = self.service.save_configuration(
            {
                "strict_grounding": False,
                "concise_answers": False,
                "unknown_setting": True,
            },
            "Use only approved internal sources.",
        )
        saved = configuration["settings"]

        self.assertFalse(saved["strict_grounding"])
        self.assertFalse(saved["concise_answers"])
        self.assertTrue(saved["show_sources"])
        self.assertNotIn("unknown_setting", saved)
        payload = json.loads(self.service.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["settings"], saved)
        self.assertEqual(payload["system_prompt"], "Use only approved internal sources.")

    def test_settings_and_prompt_are_saved_as_one_configuration(self) -> None:
        self.service.save_configuration(
            {"strict_grounding": False},
            "Use only approved internal sources.",
        )
        with patch.object(
            self.service,
            "_read_payload",
            wraps=self.service._read_payload,
        ) as read_payload:
            configuration = self.service.get_configuration()

        self.assertFalse(configuration["settings"]["strict_grounding"])
        self.assertEqual(configuration["system_prompt"], "Use only approved internal sources.")
        read_payload.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
