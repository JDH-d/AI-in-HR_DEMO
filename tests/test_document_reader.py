import json
import shutil
import unittest
from pathlib import Path

from services.document_reader import load_documents


class DocumentReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_test_runs" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        (self.temp_dir / "nested").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_load_documents_uses_relative_source_path(self) -> None:
        doc_path = self.temp_dir / "nested" / "Payroll_FAQ.md"
        doc_path.write_text("Payroll happens twice per month.", encoding="utf-8")

        docs = load_documents(self.temp_dir)

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source"], "nested/Payroll_FAQ.md")
        self.assertIn("Payroll happens twice per month.", docs[0]["text"])

    def test_load_documents_applies_catalog_metadata(self) -> None:
        doc_path = self.temp_dir / "Policy.md"
        doc_path.write_text("# Company\n\n## Leave Policy\n\nPolicy content.", encoding="utf-8")
        (self.temp_dir / "catalog.json").write_text(
            json.dumps(
                {
                    "documents": {
                        "Policy.md": {
                            "title": "Approved Leave Policy",
                            "category": "Leave",
                            "version": "2026.2",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

        docs = load_documents(self.temp_dir)

        self.assertEqual(docs[0]["title"], "Approved Leave Policy")
        self.assertEqual(docs[0]["category"], "Leave")
        self.assertEqual(docs[0]["version"], "2026.2")

    def test_load_documents_skips_duplicate_content(self) -> None:
        (self.temp_dir / "first.md").write_text("Same policy content.", encoding="utf-8")
        (self.temp_dir / "second.txt").write_text("Same   policy content.", encoding="utf-8")

        docs = load_documents(self.temp_dir)

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source"], "first.md")


if __name__ == "__main__":
    unittest.main()
