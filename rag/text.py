from __future__ import annotations

import re
from typing import TypedDict


class SectionChunk(TypedDict):
    section: str
    text: str


_KEYWORD_STOP_WORDS = {
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


def chunk_document(
    text: str,
    max_words: int = 220,
    overlap_words: int = 35,
) -> list[SectionChunk]:
    sections = _split_sections(text)
    chunks: list[SectionChunk] = []
    for section, section_text in sections:
        words = re.findall(r"\S+", section_text)
        if not words:
            continue
        start = 0
        while start < len(words):
            end = min(start + max_words, len(words))
            chunks.append({"section": section, "text": " ".join(words[start:end])})
            if end == len(words):
                break
            start = max(0, end - overlap_words)
    return chunks


def extract_keywords(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+(?:[/-][a-z0-9]+)?", (text or "").lower())
    return list(dict.fromkeys(word for word in words if word not in _KEYWORD_STOP_WORDS))


def _split_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current_section = "Document overview"
    current_lines: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if content:
            sections.append((current_section, content))

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^#{2,6}\s+(.+?)\s*$", line)
        if heading:
            flush()
            current_section = heading.group(1).strip()
            current_lines = []
            continue
        if line.startswith("# "):
            continue
        current_lines.append(raw_line)

    flush()
    return sections
