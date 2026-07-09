from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import HTTPException, UploadFile

from core.settings import SUPPORTED_DOC_EXTENSIONS
from rag.nlp import SUPPORTED_TOPICS

from .document_reader import load_documents


class DocumentService:
    def __init__(self, documents_dir: Path) -> None:
        self.documents_dir = documents_dir

    def list_documents(self) -> List[dict]:
        if not self.documents_dir.is_dir():
            return []

        metadata_by_source = {
            document["source"]: document for document in load_documents(self.documents_dir)
        }
        docs: List[dict] = []
        for root, _, files in os.walk(self.documents_dir):
            for name in files:
                path = Path(root) / name
                if path.suffix.lower() not in SUPPORTED_DOC_EXTENSIONS:
                    continue
                rel = path.relative_to(self.documents_dir).as_posix()
                stats = path.stat()
                metadata = metadata_by_source.get(rel, {})
                docs.append(
                    {
                        "name": rel,
                        "title": metadata.get("title", path.stem.replace("_", " ")),
                        "category": metadata.get("category", "General"),
                        "version": metadata.get("version", "unversioned"),
                        "size": stats.st_size,
                        "modified": datetime.fromtimestamp(
                            stats.st_mtime, timezone.utc
                        ).isoformat(),
                    }
                )
        docs.sort(key=lambda item: item["name"])
        return docs

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
        with target.open("wb") as handle:
            handle.write(file.file.read())
        return safe_name

    def delete_document(self, name: str) -> None:
        path = self.resolve_path(name)
        if not path.exists():
            raise HTTPException(
                status_code=404, detail="The requested document could not be found."
            )
        path.unlink()

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
