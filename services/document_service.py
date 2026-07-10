from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import HTTPException, UploadFile

from core.settings import SUPPORTED_DOC_EXTENSIONS
from rag.nlp import SUPPORTED_TOPICS

from .document_reader import load_documents

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


class DocumentService:
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

    def path_by_id(self, document_id: str) -> Path | None:
        document = self.find_by_id(document_id)
        return self.resolve_path(document["name"]) if document else None

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
        self.index_status_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.index_status_path.with_suffix(f"{self.index_status_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(statuses, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.index_status_path)

    def _read_index_metadata(self) -> dict[str, dict]:
        if self.index_path is None:
            return {}
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            items = payload.get("items", [])
            indexed_at = datetime.fromtimestamp(
                self.index_path.stat().st_mtime,
                timezone.utc,
            ).isoformat()
        except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
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
        try:
            payload = json.loads(self.index_status_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def save_upload(self, file: UploadFile) -> str:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in SUPPORTED_DOC_EXTENSIONS:
            raise HTTPException(
                status_code=400, detail="Unsupported document type. Use txt, md, pdf, or docx."
            )
        safe_name = Path(file.filename or "").name
        if not safe_name:
            raise HTTPException(status_code=400, detail="A valid document name is required.")
        self.documents_dir.mkdir(parents=True, exist_ok=True)
        target = self.documents_dir / safe_name
        if target.exists():
            raise HTTPException(
                status_code=409,
                detail="A document with this name already exists. Rename the file before uploading.",
            )
        content = file.file.read(MAX_DOCUMENT_BYTES + 1)
        if not content:
            raise HTTPException(status_code=400, detail="The uploaded document is empty.")
        if len(content) > MAX_DOCUMENT_BYTES:
            raise HTTPException(
                status_code=413,
                detail="The document is larger than the 10 MB upload limit.",
            )
        with target.open("wb") as handle:
            handle.write(content)
        return safe_name

    def delete_document(self, name: str) -> None:
        path = self.resolve_path(name)
        if not path.exists():
            raise HTTPException(
                status_code=404, detail="The requested document could not be found."
            )
        path.unlink()

    def remove_index_status(self, document_id: str) -> None:
        if self.index_status_path is None:
            return
        statuses = self._read_index_statuses()
        if statuses.pop(document_id, None) is None:
            return
        self.index_status_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.index_status_path.with_suffix(f"{self.index_status_path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(statuses, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.index_status_path)

    def resolve_path(self, name: str) -> Path:
        normalized = Path(os.path.normpath(name).lstrip("\\/"))
        candidate = (self.documents_dir / normalized).resolve()
        docs_root = self.documents_dir.resolve()
        if docs_root == candidate or docs_root not in candidate.parents:
            raise HTTPException(status_code=400, detail="The requested document path is invalid.")
        return candidate

    @staticmethod
    def is_numeric_topic_choice(text: str) -> bool:
        return bool(re.match(r"^\s*\d+\s*[).:\-]?\s*$", text or ""))

    @staticmethod
    def is_exact_topic_text(text: str) -> bool:
        cleaned = (text or "").strip().lower()
        return any(cleaned == topic.lower() for topic in SUPPORTED_TOPICS)

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        words = re.findall(r"[a-z0-9]+(?:[/-][a-z0-9]+)?", (text or "").lower())
        stop = {
            "the",
            "and",
            "for",
            "with",
            "that",
            "this",
            "from",
            "about",
            "into",
            "you",
            "your",
            "are",
            "can",
            "how",
            "what",
            "which",
            "when",
            "where",
            "want",
            "know",
            "info",
            "information",
            "policy",
            "policies",
        }
        return list(dict.fromkeys(word for word in words if word not in stop))
