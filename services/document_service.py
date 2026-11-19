import logging
from collections.abc import Callable
from pathlib import Path
from threading import RLock
from typing import BinaryIO

from domain.errors import DocumentError
from storage.ai_settings_store import AISettingsStore
from storage.document_store import DocumentStore

logger = logging.getLogger(__name__)


class DocumentService:
    """Coordinate library changes and indexing; all file access belongs to the store."""

    def __init__(
        self, store: DocumentStore, settings: AISettingsStore, rebuild: Callable[[], None]
    ):
        self.store = store
        self.settings = settings
        self.rebuild = rebuild
        self._lock = RLock()

    def list_documents(self) -> list[dict]:
        with self._lock:
            return self.store.list_documents()

    def _get(self, document_id: str) -> dict:
        document = self.store.find_by_id(document_id)
        if document is None:
            raise DocumentError("not_found", "The document could not be found.")
        return document

    def upload(self, filename: str, stream: BinaryIO) -> dict:
        with self._lock:
            name = self.store.save_upload(filename, stream)
            document_id = self.store.document_id(name)
            if self.settings.get()["auto_index_uploads"]:
                return self.index(document_id)
            return self._get(document_id)

    def download_path(self, document_id: str) -> Path:
        with self._lock:
            return self.store.resolve_path(self._get(document_id)["name"])

    def index(self, document_id: str) -> dict:
        with self._lock:
            document = self._get(document_id)
            self.store.record_index_result(document_id, "indexing")
            try:
                self.rebuild()
            except (RuntimeError, OSError, ValueError) as exc:
                self.store.record_index_result(
                    document_id,
                    "error",
                    "Index rebuild failed. Check the document and AI configuration, then retry.",
                )
                logger.warning(
                    "Document index rebuild failed document_id=%s error_type=%s",
                    document_id,
                    type(exc).__name__,
                )
                raise DocumentError(
                    "unavailable",
                    "Index rebuild failed. Check document readability and OpenAI configuration.",
                ) from exc
            self.store.record_index_result(document_id, "indexed")
            return self.store.find_by_id(document_id) or document

    def delete(self, document_id: str) -> None:
        with self._lock:
            document = self._get(document_id)
            try:
                with self.store.removing_document(document["name"]):
                    self.rebuild()
            except (RuntimeError, OSError, ValueError) as exc:
                logger.warning(
                    "Document deletion rolled back document_id=%s error_type=%s",
                    document_id,
                    type(exc).__name__,
                )
                raise DocumentError(
                    "unavailable",
                    "The document could not be removed from the knowledge index. Deletion was rolled back.",
                ) from exc
            self.store.remove_index_status(document_id)
