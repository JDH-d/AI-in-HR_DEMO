from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict


logger = logging.getLogger(__name__)


class DocumentRecord(TypedDict):
    source: str
    text: str


def read_document(path: Path) -> str:
    ext = path.suffix.lower()
    try:
        if ext in {".txt", ".md"}:
            return path.read_text(encoding="utf-8")
        if ext == ".docx":
            try:
                from docx import Document
            except ImportError:
                logger.warning("Skipping DOCX document because python-docx is not installed: %s", path)
                return ""
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text)
        if ext == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError:
                logger.warning("Skipping PDF document because pypdf is not installed: %s", path)
                return ""
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
    except (OSError, ValueError) as exc:
        logger.warning("Skipping unreadable document %s: %s", path, exc)
        return ""
    return ""


def load_documents(folder: Path) -> list[DocumentRecord]:
    if not folder.is_dir():
        return []

    docs: list[DocumentRecord] = []
    for path in folder.rglob("*"):
        if not path.is_file():
            continue
        text = read_document(path)
        if not text:
            continue
        docs.append({"source": path.relative_to(folder).as_posix(), "text": text})
    return docs
