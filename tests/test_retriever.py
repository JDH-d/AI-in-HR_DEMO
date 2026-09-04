import unittest
from unittest.mock import Mock

from rag.retriever import Retriever, build_relevant_excerpt


class RetrieverTests(unittest.TestCase):
    def test_query_uses_the_configured_embedding_model(self) -> None:
        client = Mock()
        client.embeddings.create.return_value = Mock(data=[Mock(embedding=[1.0, 0.0])])
        retriever = Retriever(
            [
                {
                    "source": "Payroll_FAQ.md",
                    "chunk_id": 0,
                    "text": "Salary timing",
                    "embedding": [1.0, 0.0],
                },
                {
                    "source": "IT_Support.md",
                    "chunk_id": 1,
                    "text": "VPN access",
                    "embedding": [0.0, 1.0],
                },
            ],
            client_factory=lambda: client,
            embedding_model="test-embedding-model",
        )

        results = retriever.query("compensation cadence", top_k=2)

        self.assertEqual([result["source"] for result in results], ["Payroll_FAQ.md"])
        client.embeddings.create.assert_called_once_with(
            model="test-embedding-model",
            input=["compensation cadence"],
        )

    def test_query_falls_back_to_lexical_matching_when_embeddings_are_unavailable(self) -> None:
        retriever = Retriever(
            [
                {
                    "source": "Payroll_FAQ.md",
                    "chunk_id": 0,
                    "text": "Salaries are paid on the fifteenth and the last business day of the month.",
                },
                {
                    "source": "IT_Support_and_Access.md",
                    "chunk_id": 1,
                    "text": "VPN access requests require business justification and manager approval when needed.",
                },
            ]
        )

        results = retriever.query(
            "How often are salaries paid?",
            top_k=2,
            use_embeddings=False,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "Payroll_FAQ.md")
        self.assertGreaterEqual(results[0]["score"], 0.25)

    def test_query_deduplicates_chunks_from_the_same_section(self) -> None:
        base = {
            "source": "Payroll_FAQ.md",
            "document_id": "payroll-faq",
            "title": "Payroll Handbook",
            "category": "Payroll",
            "version": "2026.1",
            "section": "Pay schedule",
        }
        retriever = Retriever(
            [
                {
                    **base,
                    "chunk_id": 0,
                    "text": "Payroll is issued twice each month on the regular schedule.",
                },
                {
                    **base,
                    "chunk_id": 1,
                    "text": "The regular payroll schedule issues pay twice each month.",
                },
            ]
        )

        results = retriever.query(
            "What is the payroll schedule?",
            top_k=4,
            min_similarity=0.1,
            use_embeddings=False,
        )

        self.assertEqual(len(results), 1)

    def test_excerpt_centers_the_matching_faq_answer(self) -> None:
        text = (
            "Unrelated introduction about payroll administration. "
            "How often are salaries paid? Salaries are paid on the fifteenth and "
            "the last business day of the month. Another unrelated sentence."
        )

        excerpt = build_relevant_excerpt(text, "How often are salaries paid?", max_chars=180)

        self.assertIn("How often are salaries paid?", excerpt)
        self.assertIn("the last business day of the month", excerpt)


if __name__ == "__main__":
    unittest.main()
