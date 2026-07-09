import unittest
from unittest.mock import patch

from rag.retriever import Retriever


class RetrieverTests(unittest.TestCase):
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

        with patch("rag.retriever.OpenAI", side_effect=OSError("no api key")):
            results = retriever.query("How often are salaries paid?", top_k=2)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "Payroll_FAQ.md")
        self.assertGreaterEqual(results[0]["score"], 0.5)


if __name__ == "__main__":
    unittest.main()
