import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from rag import index
from services.document_reader import load_documents


class IndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path.cwd() / ".tmp_test_runs" / self._testMethodName
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.documents_dir = self.temp_dir / "documents"
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        (self.documents_dir / "Policy.md").write_text(
            "# Company\n\n## Password Reset\n\nUse the approved reset workflow.",
            encoding="utf-8",
        )
        self.index_path = self.temp_dir / "index.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_build_index_writes_versioned_metadata_payload(self) -> None:
        documents = load_documents(self.documents_dir)
        with (
            patch.object(index, "INDEX_PATH", self.index_path),
            patch.object(index, "_add_embeddings"),
        ):
            index.build_index(documents)

        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        item = payload["items"][0]
        self.assertEqual(payload["schema_version"], index.INDEX_SCHEMA_VERSION)
        self.assertEqual(item["section"], "Password Reset")
        self.assertEqual(item["title"], "Company")
        self.assertEqual(item["category"], "General")
        self.assertEqual(item["version"], "unversioned")

    def test_documents_fingerprint_changes_with_metadata(self) -> None:
        documents = load_documents(self.documents_dir)
        initial = index.documents_fingerprint(documents)
        documents[0]["version"] = "2026.2"

        updated = index.documents_fingerprint(documents)

        self.assertNotEqual(initial, updated)


if __name__ == "__main__":
    unittest.main()
