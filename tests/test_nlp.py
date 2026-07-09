import unittest

from rag.nlp import Intent, detect_intent, detect_topic_selection
from web_ui.streamlit_app import DEMO_PROMPTS


class NLPDetectionTests(unittest.TestCase):
    def test_vacation_request_is_not_topic_selection(self) -> None:
        self.assertIsNone(detect_topic_selection("I need vacation from 01/04 to 03/04"))

    def test_short_topic_alias_is_topic_selection(self) -> None:
        self.assertEqual(
            detect_topic_selection("pto"),
            "PTO, vacation, and sick leave",
        )

    def test_salary_question_is_work_intent(self) -> None:
        self.assertEqual(
            detect_intent("How often are salaries paid?"),
            Intent.WORK,
        )

    def test_password_question_is_work_intent(self) -> None:
        self.assertEqual(
            detect_intent("What should I do if I forget my password?"),
            Intent.WORK,
        )

    def test_late_absence_question_is_work_intent(self) -> None:
        self.assertEqual(
            detect_intent("How should I report being late or unexpectedly absent?"),
            Intent.WORK,
        )

    def test_small_talk_is_not_promoted_to_work(self) -> None:
        self.assertEqual(detect_intent("hello"), Intent.SMALL_TALK)

    def test_supported_demo_prompts_are_never_routed_as_invalid(self) -> None:
        unsupported = {
            "Write me a poem about dragons.",
            "What's the weather in Los Angeles today?",
        }

        for _, prompts in DEMO_PROMPTS:
            for prompt in prompts:
                intent = detect_intent(prompt)
                if prompt in unsupported:
                    self.assertEqual(intent, Intent.INVALID, prompt)
                else:
                    self.assertNotEqual(intent, Intent.INVALID, prompt)

    def test_later_does_not_match_late_attendance_keyword(self) -> None:
        self.assertEqual(detect_intent("Can we talk later?"), Intent.INVALID)


if __name__ == "__main__":
    unittest.main()
