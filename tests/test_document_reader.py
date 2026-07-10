import json
import shutil
import unittest
from pathlib import Path

from services.document_reader import load_documents
from services.document_service import DocumentService


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

    def test_uploaded_markdown_uses_first_h1_as_document_title(self) -> None:
        (self.temp_dir / "Custom.md").write_text(
            "# Custom Handbook\n\n## Internal section\n\nPolicy content.",
            encoding="utf-8",
        )

        docs = load_documents(self.temp_dir)

        self.assertEqual(docs[0]["title"], "Custom Handbook")

    def test_load_documents_skips_duplicate_content(self) -> None:
        (self.temp_dir / "first.md").write_text("Same policy content.", encoding="utf-8")
        (self.temp_dir / "second.txt").write_text("Same   policy content.", encoding="utf-8")

        docs = load_documents(self.temp_dir)

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["source"], "first.md")

    def test_document_service_reports_index_health(self) -> None:
        (self.temp_dir / "Policy.md").write_text("Policy content.", encoding="utf-8")
        index_path = self.temp_dir / "index.json"
        index_path.write_text(
            json.dumps(
                {
                    "items": [
                        {"source": "Policy.md"},
                        {"source": "Policy.md"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        service = DocumentService(
            self.temp_dir,
            index_path=index_path,
            index_status_path=self.temp_dir / "index_status.json",
        )

        document = service.list_documents()[0]

        self.assertEqual(document["index_status"], "indexed")
        self.assertEqual(document["chunk_count"], 2)
        self.assertIsNotNone(document["indexed_at"])


if __name__ == "__main__":
    unittest.main()
