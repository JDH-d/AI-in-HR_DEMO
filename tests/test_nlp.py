import unittest

from demo_prompts import DEMO_PROMPTS

from rag.nlp import Intent, detect_intent, detect_topic_selection


class NLPDetectionTests(unittest.TestCase):
    def test_vacation_request_is_not_topic_selection(self) -> None:
        self.assertIsNone(detect_topic_selection("I need vacation from 2030-04-01 to 2030-04-03"))

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

    def test_payday_follow_up_accepts_plural_and_spaced_forms(self) -> None:
        for question in (
            "When is payday?",
            "How many paydays are there each month?",
            "How many pay days are there each month?",
        ):
            with self.subTest(question=question):
                self.assertEqual(detect_intent(question), Intent.WORK)

    def test_late_absence_question_is_work_intent(self) -> None:
        self.assertEqual(
            detect_intent("How should I report being late or unexpectedly absent?"),
            Intent.WORK,
        )

    def test_small_talk_is_not_promoted_to_work(self) -> None:
        self.assertEqual(detect_intent("hello"), Intent.SMALL_TALK)

    def test_greeting_does_not_hide_a_work_question(self) -> None:
        for greeting in ("Hello,", "Hi!", "Hey there.", "Good morning,"):
            with self.subTest(greeting=greeting):
                self.assertEqual(
                    detect_intent(f"{greeting} How often are salaries paid?"), Intent.WORK
                )

    def test_greeting_does_not_turn_an_unknown_question_into_small_talk(self) -> None:
        self.assertEqual(detect_intent("Hello, when does the money land?"), Intent.INVALID)

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
