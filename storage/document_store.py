from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, List

from core.settings import MAX_DOCUMENT_BYTES, SUPPORTED_DOC_EXTENSIONS
from domain.errors import DocumentError
from storage.document_reader import load_documents
from storage.json_store import read_json, write_json


class DocumentStore:
    def __init__(
        self,
        documents_dir: Path,
        index_path: Path | None = None,
        index_status_path: Path | None = None,
    ) -> None:
        self.documents_dir = documents_dir
        self.index_path = index_path
        self.index_status_path = index_status_path

    def list_documents(self) -> List[dict]:
        if not self.documents_dir.is_dir():
            return []

        metadata_by_source = {
            document["source"]: document for document in load_documents(self.documents_dir)
        }
        index_metadata = self._read_index_metadata()
        recorded_statuses = self._read_index_statuses()
        docs: List[dict] = []
        for root, _, files in os.walk(self.documents_dir):
            for name in files:
                path = Path(root) / name
                if path.suffix.lower() not in SUPPORTED_DOC_EXTENSIONS:
                    continue
                rel = path.relative_to(self.documents_dir).as_posix()
                stats = path.stat()
                metadata = metadata_by_source.get(rel, {})
                document_id = self.document_id(rel)
                indexed = index_metadata.get(rel, {})
                recorded = recorded_statuses.get(document_id, {})
                docs.append(
                    {
                        "id": document_id,
                        "name": rel,
                        "title": metadata.get("title", path.stem.replace("_", " ")),
                        "category": metadata.get("category", "General"),
                        "version": metadata.get("version", "unversioned"),
                        "size": stats.st_size,
                        "modified": datetime.fromtimestamp(
                            stats.st_mtime, timezone.utc
                        ).isoformat(),
                        "index_status": recorded.get(
                            "status",
                            "indexed" if indexed.get("chunk_count", 0) else "pending",
                        ),
                        "chunk_count": indexed.get("chunk_count", 0),
                        "indexed_at": recorded.get("updated_at") or indexed.get("indexed_at"),
                        "index_error": recorded.get("error"),
                    }
                )
        docs.sort(key=lambda item: item["name"])
        return docs

    @staticmethod
    def document_id(name: str) -> str:
        return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]

    def find_by_id(self, document_id: str) -> dict | None:
        return next(
            (document for document in self.list_documents() if document["id"] == document_id),
            None,
        )

    def record_index_result(
        self,
        document_id: str,
        status: str,
        error: str | None = None,
    ) -> None:
        if self.index_status_path is None:
            return
        statuses = self._read_index_statuses()
        statuses[document_id] = {
            "status": status,
            "error": error,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        write_json(self.index_status_path, statuses)

    def _read_index_metadata(self) -> dict[str, dict]:
        if self.index_path is None:
            return {}
        try:
            payload = read_json(self.index_path, {})
            items = payload.get("items", [])
            indexed_at = datetime.fromtimestamp(
                self.index_path.stat().st_mtime,
                timezone.utc,
            ).isoformat()
        except (OSError, AttributeError):
            return {}
        metadata: dict[str, dict] = {}
        for item in items if isinstance(items, list) else []:
            source = str(item.get("source", ""))
            if not source:
                continue
            entry = metadata.setdefault(
                source,
                {"chunk_count": 0, "indexed_at": indexed_at},
            )
            entry["chunk_count"] += 1
        return metadata

    def _read_index_statuses(self) -> dict[str, dict]:
        if self.index_status_path is None:
            return {}
        payload = read_json(self.index_status_path, {})
        return payload if isinstance(payload, dict) else {}

    def save_upload(self, filename: str, stream: BinaryIO) -> str:
        ext = Path(filename or "").suffix.lower()
        if ext not in SUPPORTED_DOC_EXTENSIONS:
            raise DocumentError(
                code="invalid", message="Unsupported document type. Use txt, md, pdf, or docx."
            )
        safe_name = Path(filename or "").name
        if not safe_name:
            raise DocumentError(code="invalid", message="A valid document name is required.")
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        target = self.documents_dir / safe_name
        if target.exists():
            raise DocumentError(
                code="conflict",
                message="A document with this name already exists. Rename the file before uploading.",
            )
        content = stream.read(MAX_DOCUMENT_BYTES + 1)
        if not content:
            raise DocumentError(code="invalid", message="The uploaded document is empty.")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise DocumentError(
                code="too_large",
                message="The document is larger than the 10 MB upload limit.",
            )
        try:
            with target.open("xb") as handle:
                handle.write(content)
        except FileExistsError as exc:
            raise DocumentError(
                code="conflict", message="A document with this name already exists."
            ) from exc
        return safe_name

    @contextmanager
    def removing_document(self, name: str):
        path = self.resolve_path(name)
        if not path.exists():
            raise DocumentError(
                code="not_found", message="The requested document could not be found."
            )
        original = path.read_bytes()
        metadata = path.stat()
        path.unlink()
        try:
            yield
        except BaseException:
            path.write_bytes(original)
            os.utime(path, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
            raise

    def remove_index_status(self, document_id: str) -> None:
        if self.index_status_path is None:
            return
        statuses = self._read_index_statuses()
        if statuses.pop(document_id, None) is None:
            return
        write_json(self.index_status_path, statuses)

    def resolve_path(self, name: str) -> Path:
        normalized = Path(os.path.normpath(name).lstrip("\\/"))
        candidate = (self.documents_dir / normalized).resolve()
        docs_root = self.documents_dir.resolve()
        if docs_root == candidate or docs_root not in candidate.parents:
            raise DocumentError(code="invalid", message="The requested document path is invalid.")
        return candidate
