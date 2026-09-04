from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from core.files import atomic_write_bytes, atomic_write_json
from core.settings import SUPPORTED_DOC_EXTENSIONS
from services.document_reader import document_id_for_source, load_document_catalog

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class DocumentError(RuntimeError):
    pass


class InvalidDocumentError(DocumentError):
    pass


class DocumentExistsError(DocumentError):
    pass


class DocumentNotFoundError(DocumentError):
    pass


class DocumentService:
    """Owns document files and their index presentation metadata."""

    def __init__(
        self,
        documents_dir: Path,
        index_path: Path | None = None,
        index_status_path: Path | None = None,
    ) -> None:
        self.documents_dir = documents_dir
        self.index_path = index_path
        self.index_status_path = index_status_path

    def list_documents(self) -> list[dict]:
        if not self.documents_dir.is_dir():
            return []

        catalog = load_document_catalog(self.documents_dir)
        index_metadata, index_mode = self._read_index_metadata()
        recorded_statuses = self._read_index_statuses()
        documents: list[dict] = []
        for root, _, files in os.walk(self.documents_dir):
            for name in files:
                path = Path(root) / name
                if path.suffix.lower() not in SUPPORTED_DOC_EXTENSIONS:
                    continue
                source = path.relative_to(self.documents_dir).as_posix()
                stats = path.stat()
                metadata = catalog.get(source, {})
                document_id = self.document_id(source)
                indexed = index_metadata.get(source, {})
                recorded = recorded_statuses.get(document_id, {})
                documents.append(
                    {
                        "id": document_id,
                        "name": source,
                        "title": metadata.get("title") or path.stem.replace("_", " "),
                        "category": metadata.get("category") or "General",
                        "version": metadata.get("version") or "unversioned",
                        "size": stats.st_size,
                        "modified": datetime.fromtimestamp(
                            stats.st_mtime,
                            timezone.utc,
                        ).isoformat(),
                        "index_status": recorded.get(
                            "status",
                            "indexed" if indexed.get("chunk_count", 0) else "pending",
                        ),
                        "index_mode": index_mode if indexed.get("chunk_count", 0) else None,
                        "chunk_count": indexed.get("chunk_count", 0),
                        "indexed_at": recorded.get("updated_at") or indexed.get("indexed_at"),
                        "index_error": recorded.get("error"),
                    }
                )
        documents.sort(key=lambda item: item["name"])
        return documents

    @staticmethod
    def document_id(name: str) -> str:
        return document_id_for_source(name)

    def find_by_id(self, document_id: str) -> dict | None:
        return next(
            (document for document in self.list_documents() if document["id"] == document_id),
            None,
        )

    def save_upload(self, filename: str, content: bytes) -> str:
        safe_name = Path(filename or "").name
        extension = Path(safe_name).suffix.lower()
        if extension not in SUPPORTED_DOC_EXTENSIONS:
            raise InvalidDocumentError("Unsupported document type. Use txt, md, pdf, or docx.")
        if not safe_name:
            raise InvalidDocumentError("A valid document name is required.")
        if not content:
            raise InvalidDocumentError("The uploaded document is empty.")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise InvalidDocumentError("The document is larger than the 10 MB upload limit.")

        target = self.resolve_path(safe_name)
        if target.exists():
            raise DocumentExistsError(
                "A document with this name already exists. Rename the file before uploading."
            )
        atomic_write_bytes(target, content)
        return safe_name

    def delete_document(self, name: str) -> bytes:
        path = self.resolve_path(name)
        if not path.exists():
            raise DocumentNotFoundError("The requested document could not be found.")
        content = path.read_bytes()
        path.unlink()
        return content

    def restore_document(self, name: str, content: bytes) -> None:
        atomic_write_bytes(self.resolve_path(name), content)

    def snapshot_index_files(self) -> dict[str, bytes | None]:
        return {
            "index": self._read_optional_bytes(self.index_path),
            "status": self._read_optional_bytes(self.index_status_path),
        }

    def restore_index_files(self, snapshot: dict[str, bytes | None]) -> None:
        for key, path in (
            ("index", self.index_path),
            ("status", self.index_status_path),
        ):
            if path is None:
                continue
            content = snapshot.get(key)
            if content is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write_bytes(path, content)

    def resolve_path(self, name: str) -> Path:
        normalized = Path(os.path.normpath(name).lstrip("\\/"))
        candidate = (self.documents_dir / normalized).resolve()
        documents_root = self.documents_dir.resolve()
        if documents_root == candidate or documents_root not in candidate.parents:
            raise InvalidDocumentError("The requested document path is invalid.")
        return candidate

    def record_all_index_results(self, status: str, error: str | None = None) -> None:
        if self.index_status_path is None:
            return
        updated_at = datetime.now(timezone.utc).isoformat()
        statuses = {
            document["id"]: {
                "status": status,
                "error": error,
                "updated_at": updated_at,
            }
            for document in self.list_documents()
        }
        atomic_write_json(self.index_status_path, statuses, indent=2)

    def index_health(self) -> dict:
        _, mode = self._read_index_metadata()
        statuses = self._read_index_statuses().values()
        return {
            "mode": mode,
            "documents_with_errors": sum(1 for item in statuses if item.get("status") == "error"),
        }

    def _read_index_metadata(self) -> tuple[dict[str, dict], str | None]:
        if self.index_path is None:
            return {}, None
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            items = payload.get("items", [])
            mode = payload.get("mode")
            indexed_at = datetime.fromtimestamp(
                self.index_path.stat().st_mtime,
                timezone.utc,
            ).isoformat()
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
            return {}, None
        metadata: dict[str, dict] = {}
        for item in items if isinstance(items, list) else []:
            source = str(item.get("source", ""))
            if not source:
                continue
            entry = metadata.setdefault(source, {"chunk_count": 0, "indexed_at": indexed_at})
            entry["chunk_count"] += 1
        return metadata, str(mode) if mode else None

    def _read_index_statuses(self) -> dict[str, dict]:
        if self.index_status_path is None:
            return {}
        try:
            payload = json.loads(self.index_status_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _read_optional_bytes(path: Path | None) -> bytes | None:
        if path is None:
            return None
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
