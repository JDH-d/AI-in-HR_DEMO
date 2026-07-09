from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from fastapi import HTTPException, UploadFile

from core.settings import SUPPORTED_DOC_EXTENSIONS

from .document_reader import read_document


TOPIC_DOC_MAP = {
    "PTO, vacation, and sick leave": "PTO_Policy.md",
    "Salary and payroll": "Payroll_FAQ.md",
    "Employee benefits": "Benefits_Enrollment_Guide.md",
    "Work schedules and shifts": "Work_Schedules_and_Shifts.md",
    "IT support (VPN, access permissions, password reset)": "IT_Support_and_Access.md",
}


class DocumentService:
    def __init__(self, documents_dir: Path) -> None:
        self.documents_dir = documents_dir

    def list_documents(self) -> List[dict]:
        docs: List[dict] = []
        if not self.documents_dir.is_dir():
            return docs
        for root, _, files in os.walk(self.documents_dir):
            for name in files:
                path = Path(root) / name
                rel = path.relative_to(self.documents_dir).as_posix()
                stats = path.stat()
                docs.append(
                    {
                        "name": rel,
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
            raise HTTPException(status_code=400, detail="Unsupported document type. Use txt, md, pdf, or docx.")
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
            raise HTTPException(status_code=404, detail="The requested document could not be found.")
        path.unlink()

    def resolve_path(self, name: str) -> Path:
        normalized = Path(os.path.normpath(name).lstrip("\\/"))
        candidate = (self.documents_dir / normalized).resolve()
        docs_root = self.documents_dir.resolve()
        if docs_root == candidate or docs_root not in candidate.parents:
            raise HTTPException(status_code=400, detail="The requested document path is invalid.")
        return candidate

    def load_text_for_topic(self, topic: str) -> str:
        file_name = TOPIC_DOC_MAP.get(topic)
        if not file_name:
            return ""
        path = self.documents_dir / file_name
        if not path.exists():
            return ""
        return read_document(path).strip()

    @staticmethod
    def is_numeric_topic_choice(text: str) -> bool:
        return bool(re.match(r"^\s*\d+\s*[).:\-]?\s*$", text or ""))

    @staticmethod
    def is_exact_topic_text(text: str) -> bool:
        cleaned = (text or "").strip().lower()
        return any(cleaned == topic.lower() for topic in TOPIC_DOC_MAP)

    def filter_doc_by_query(self, doc_text: str, query: str, max_lines: int = 4) -> str:
        return "\n".join(self._collect_relevant_lines(doc_text, query, max_lines=max_lines))

    def build_topic_prompt_context(
        self,
        doc_text: str,
        query: str,
        max_lines: int = 6,
    ) -> str:
        if not doc_text:
            return ""
        relevant_text = self.filter_doc_by_query(doc_text, query, max_lines=max_lines)
        return relevant_text or doc_text

    def _collect_relevant_lines(
        self,
        doc_text: str,
        query: str,
        max_lines: int,
    ) -> List[str]:
        if not doc_text:
            return []

        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        lines = [line.strip() for line in doc_text.splitlines() if line.strip()]
        scored_matches: List[tuple[int, int]] = []
        for idx, line in enumerate(lines):
            low = line.lower()
            score = sum(1 for keyword in keywords if keyword in low)
            if score > 0:
                scored_matches.append((score, idx))

        if not scored_matches:
            return []

        selected_indices: set[int] = set()
        for _, idx in sorted(scored_matches, key=lambda item: (-item[0], item[1])):
            selected_indices.add(idx)
            if idx > 0 and self._is_heading_line(lines[idx - 1]):
                selected_indices.add(idx - 1)
            if self._is_heading_line(lines[idx]) and idx + 1 < len(lines):
                selected_indices.add(idx + 1)
            if len(selected_indices) >= max_lines:
                break

        ordered_indices = sorted(selected_indices)[:max_lines]
        return [lines[idx] for idx in ordered_indices]

    @staticmethod
    def _is_heading_line(text: str) -> bool:
        return text.startswith("#")

    @staticmethod
    def _extract_keywords(text: str) -> List[str]:
        cleaned = (text or "").lower()
        words = re.findall(r"[a-z]{3,}", cleaned)
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
        keywords = [word for word in words if word not in stop]
        if "pto" in cleaned or "paid time off" in cleaned:
            keywords.extend(["pto", "paid time off"])
        if "sick" in cleaned and "leave" in cleaned:
            keywords.append("sick leave")
        if "vacation" in cleaned:
            keywords.append("vacation")
        if "salary" in cleaned:
            keywords.append("salary")
        if "payroll" in cleaned:
            keywords.append("payroll")
        if "benefits" in cleaned:
            keywords.append("benefits")
        if "schedule" in cleaned or "shift" in cleaned:
            keywords.extend(["schedule", "shift"])
        if "vpn" in cleaned:
            keywords.append("vpn")
        if "access" in cleaned:
            keywords.append("access")
        if "password" in cleaned:
            keywords.append("password")

        seen = set()
        unique: List[str] = []
        for keyword in keywords:
            if keyword in seen:
                continue
            seen.add(keyword)
            unique.append(keyword)
        return unique
