from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import TypedDict

from core.settings import SUPPORTED_DOC_EXTENSIONS

logger = logging.getLogger(__name__)

CATALOG_FILE_NAME = "catalog.json"


class DocumentRecord(TypedDict):
    source: str
    document_id: str
    title: str
    category: str
    version: str
    text: str
    content_hash: str


class DocumentReadError(RuntimeError):
    def __init__(self, path: Path, reason: str) -> None:
        self.path = path
        super().__init__(f"Unable to read {path.name}: {reason}")


def document_id_for_source(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]


def read_document(path: Path, *, strict: bool = False) -> str:
    ext = path.suffix.lower()
    try:
        if ext in {".txt", ".md"}:
            return path.read_text(encoding="utf-8")
        if ext == ".docx":
            try:
                from docx import Document
            except ImportError:
                return _unreadable(
                    path,
                    "python-docx is not installed",
                    strict=strict,
                )
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text)
        if ext == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                return _unreadable(path, "pypdf is not installed", strict=strict)
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        return _unreadable(path, f"{type(exc).__name__}: {exc}", strict=strict)
    return ""


def load_document_catalog(folder: Path) -> dict[str, dict[str, str]]:
    path = folder / CATALOG_FILE_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Ignoring invalid document catalog %s: %s", path, exc)
        return {}

    documents = payload.get("documents", {})
    if not isinstance(documents, dict):
        logger.warning("Ignoring document catalog with invalid documents mapping: %s", path)
        return {}
    return {
        str(source): {
            "title": str(metadata.get("title", "")).strip(),
            "category": str(metadata.get("category", "")).strip(),
            "version": str(metadata.get("version", "")).strip(),
        }
        for source, metadata in documents.items()
        if isinstance(metadata, dict)
    }


def load_documents(folder: Path, *, strict: bool = False) -> list[DocumentRecord]:
    if not folder.is_dir():
        return []

    catalog = load_document_catalog(folder)
    docs: list[DocumentRecord] = []
    seen_hashes: dict[str, str] = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_DOC_EXTENSIONS:
            continue
        text = read_document(path, strict=strict).strip()
        if not text:
            if strict:
                raise DocumentReadError(path, "the document contains no readable text")
            continue

        source = path.relative_to(folder).as_posix()
        content_hash = _content_hash(text)
        duplicate_source = seen_hashes.get(content_hash)
        if duplicate_source:
            logger.warning(
                "Skipping duplicate document source=%s duplicate_of=%s",
                source,
                duplicate_source,
            )
            continue
        seen_hashes[content_hash] = source

        metadata = catalog.get(source, {})
        docs.append(
            {
                "source": source,
                "document_id": document_id_for_source(source),
                "title": metadata.get("title") or _extract_title(text, Path(source).stem),
                "category": metadata.get("category") or "General",
                "version": metadata.get("version") or "unversioned",
                "text": text,
                "content_hash": content_hash,
            }
        )
    return docs


def _unreadable(path: Path, reason: str, *, strict: bool) -> str:
    error = DocumentReadError(path, reason)
    if strict:
        raise error
    logger.warning("Skipping unreadable document %s: %s", path, reason)
    return ""


def _extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        heading = re.match(r"^#\s+(.+?)\s*$", line)
        if heading:
            return heading.group(1).strip()
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            return heading.group(1).strip()
    return fallback.replace("_", " ").strip()


def _content_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
