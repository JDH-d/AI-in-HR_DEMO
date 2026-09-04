import unittest

from rag.nlp import Intent
from services.chat_models import ChatQuery, ChatTurn
from services.chat_router import ChatRouter


class ChatRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = ChatRouter()

    @staticmethod
    def _guided_salary_reply() -> str:
        return (
            "You selected Salary and payroll. What would you like to know?\n"
            "Examples:\n"
            "- How often are salaries paid?\n"
            "- When is payroll processed?\n"
            "- Who should I contact about a payroll issue?"
        )

    def test_follow_up_question_promotes_prior_topic_to_work(self) -> None:
        query = ChatQuery(
            messages=[
                ChatTurn(role="user", content="2"),
                ChatTurn(role="assistant", content=self._guided_salary_reply()),
                ChatTurn(role="user", content="How often are they paid?"),
            ]
        )

        decision = self.router.route(query)

        self.assertEqual(decision.intent, Intent.WORK)
        self.assertEqual(decision.prior_topic, "Salary and payroll")

    def test_irrelevant_joke_request_does_not_reuse_prior_topic(self) -> None:
        query = ChatQuery(
            messages=[
                ChatTurn(role="user", content="2"),
                ChatTurn(role="assistant", content=self._guided_salary_reply()),
                ChatTurn(role="user", content="Tell me a joke"),
            ]
        )

        decision = self.router.route(query)

        self.assertEqual(decision.intent, Intent.INVALID)
        self.assertEqual(decision.prior_topic, "Salary and payroll")


if __name__ == "__main__":
    unittest.main()
