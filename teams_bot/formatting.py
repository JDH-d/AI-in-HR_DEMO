from __future__ import annotations

import re
from html import unescape
from pathlib import Path

from api.schemas import ChatResponse


def normalize_teams_text(text: str | None) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


def format_chat_response(response: ChatResponse, max_sources: int = 3) -> str:
    answer = response.message.content.strip()
    sources = response.sources or []
    if not sources or max_sources <= 0:
        return answer

    lines: list[str] = ["", "**Sources**"]
    seen: set[tuple[str, int]] = set()
    count = 0
    for source in sources:
        key = (source.source, source.chunk_id)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        label = Path(source.source).name
        lines.append(
            f"{count}. {label} - chunk {source.chunk_id}, score {source.score:.2f}"
        )
        if count >= max_sources:
            break

    return answer + "\n".join(lines)
