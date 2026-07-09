from __future__ import annotations

import re
from typing import TypedDict


class SectionChunk(TypedDict):
    section: str
    text: str


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


def chunk_text(text: str, max_words: int = 220, overlap_words: int = 35) -> list[str]:
    return [
        item["text"]
        for item in chunk_document(
            text,
            max_words=max_words,
            overlap_words=overlap_words,
        )
    ]


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
