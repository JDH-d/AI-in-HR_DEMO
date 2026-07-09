import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rag.nlp import Intent
from services.chat_fallbacks import ChatFallbackPolicy
from services.chat_models import ChatQuery, ChatTurn, RoutingDecision
from services.document_service import DocumentService
from services.llm_service import LLMServiceError
from services.rag_service import RAGService


class FailingLLM:
    def generate(self, prompt_messages: list[dict]) -> str:
        raise LLMServiceError("LLM unavailable")


class RAGServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / '.tmp_test_runs' / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        (self.temp_dir / 'documents').mkdir(parents=True, exist_ok=True)
        self.rag_service = RAGService(
            llm_service=FailingLLM(),
            document_service=DocumentService(self.temp_dir / 'documents'),
            fallback_policy=ChatFallbackPolicy(),
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_answer_with_retrieval_uses_extractive_fallback_when_llm_is_unavailable(self) -> None:
        query = ChatQuery(messages=[ChatTurn(role='user', content='How often are salaries paid?')])
        decision = RoutingDecision(
            language='en',
            intent=Intent.WORK,
            topic_selection=None,
            explicit_topic_choice=False,
            prior_topic=None,
        )
        retriever = Mock()
        retriever.query.return_value = [
            {
                'source': 'Payroll_FAQ.md',
                'chunk_id': 0,
                'text': 'Salaries are paid on the fifteenth and the last business day of the month. Direct deposit is the standard payment method.',
                'score': 0.82,
            }
        ]

        with patch('services.rag_service.ensure_index'), patch('services.rag_service.get_retriever', return_value=retriever):
            outcome = self.rag_service.answer_with_retrieval(query, decision)

        self.assertIn('Salaries are paid on the fifteenth and the last business day of the month.', outcome.content)
        self.assertEqual(len(outcome.sources), 1)
        self.assertEqual(outcome.sources[0].source, 'Payroll_FAQ.md')


if __name__ == '__main__':
    unittest.main()
