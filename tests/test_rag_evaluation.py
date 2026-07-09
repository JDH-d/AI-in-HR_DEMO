import unittest
from pathlib import Path

from scripts.run_rag_eval import evaluate_cases, load_cases


class RAGEvaluationTests(unittest.TestCase):
    def test_offline_rag_evaluation_passes(self) -> None:
        root = Path(__file__).resolve().parents[1]

        report = evaluate_cases(
            load_cases(root / "evals" / "rag_questions.json"),
            root / "documents",
        )

        self.assertEqual(report["total"], 42)
        self.assertEqual(report["passed"], report["total"])


if __name__ == "__main__":
    unittest.main()
