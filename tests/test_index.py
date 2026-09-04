import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from rag import index
from rag.index import KnowledgeIndex
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
        knowledge_index = KnowledgeIndex(
            self.documents_dir,
            self.index_path,
            "test-embedding-model",
            client_factory=lambda: (_ for _ in ()).throw(ValueError("offline")),
        )

        knowledge_index.build(documents)

        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        item = payload["items"][0]
        self.assertEqual(payload["schema_version"], index.INDEX_SCHEMA_VERSION)
        self.assertEqual(payload["mode"], "lexical")
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

    def test_lexical_fallback_retries_embeddings_after_cooldown(self) -> None:
        state = {"available": False}
        client = Mock()
        client.embeddings.create.return_value = Mock(data=[Mock(embedding=[0.2, 0.8])])

        def client_factory():
            if not state["available"]:
                raise ValueError("offline")
            return client

        knowledge_index = KnowledgeIndex(
            self.documents_dir,
            self.index_path,
            "test-embedding-model",
            client_factory=client_factory,
            embedding_retry_seconds=300,
        )
        with patch("rag.index.time.time", return_value=1_000.0):
            first = knowledge_index.build()
        state["available"] = True
        with patch("rag.index.time.time", return_value=1_301.0):
            knowledge_index.ensure()

        retried = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.assertEqual(first["mode"], "lexical")
        self.assertEqual(retried["mode"], "embedding")
        self.assertEqual(retried["items"][0]["embedding"], [0.2, 0.8])

    def test_matching_but_incomplete_embedding_index_is_rebuilt(self) -> None:
        knowledge_index = KnowledgeIndex(
            self.documents_dir,
            self.index_path,
            "test-embedding-model",
            client_factory=lambda: (_ for _ in ()).throw(ValueError("offline")),
        )
        payload = knowledge_index.build()
        payload["mode"] = "embedding"
        self.index_path.write_text(json.dumps(payload), encoding="utf-8")

        knowledge_index.ensure()

        repaired = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.assertEqual(repaired["mode"], "lexical")
        self.assertNotIn("embedding", repaired["items"][0])

    def test_embedding_index_with_invalid_vector_is_rebuilt(self) -> None:
        knowledge_index = KnowledgeIndex(
            self.documents_dir,
            self.index_path,
            "test-embedding-model",
            client_factory=lambda: (_ for _ in ()).throw(ValueError("offline")),
        )
        payload = knowledge_index.build()
        payload["mode"] = "embedding"
        payload["items"][0]["embedding"] = []
        self.index_path.write_text(json.dumps(payload), encoding="utf-8")

        knowledge_index.ensure()

        repaired = json.loads(self.index_path.read_text(encoding="utf-8"))
        self.assertEqual(repaired["mode"], "lexical")
        self.assertNotIn("embedding", repaired["items"][0])

    def test_invalid_provider_embedding_is_not_written_to_the_index(self) -> None:
        client = Mock()
        client.embeddings.create.return_value = Mock(data=[Mock(embedding=[])])
        knowledge_index = KnowledgeIndex(
            self.documents_dir,
            self.index_path,
            "test-embedding-model",
            client_factory=lambda: client,
        )

        payload = knowledge_index.build()

        self.assertEqual(payload["mode"], "lexical")
        self.assertNotIn("embedding", payload["items"][0])


if __name__ == "__main__":
    unittest.main()
