from __future__ import annotations

import re
from typing import List


def chunk_text(text: str, max_words: int = 200, overlap_words: int = 40) -> List[str]:
    words = re.findall(r"\S+", text)
    if not words:
        return []

    chunks: List[str] = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(0, end - overlap_words)
    return chunks

