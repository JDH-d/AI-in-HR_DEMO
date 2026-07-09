from __future__ import annotations

from pathlib import Path
from typing import List

from core.settings import SYSTEM_PROMPT_PATH

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional internal knowledge and workflow assistant for a company demo. "
    "Use the configured company documents as the source of truth. "
    "Be concise, accurate, and businesslike. Do not invent policies or process details."
)


def load_system_prompt() -> str:
    path = Path(SYSTEM_PROMPT_PATH)
    try:
        content = path.read_text(encoding="utf-8").strip()
        if content:
            return content
    except FileNotFoundError:
        pass
    return DEFAULT_SYSTEM_PROMPT


def save_system_prompt(text: str) -> None:
    path = Path(SYSTEM_PROMPT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip(), encoding="utf-8")


def build_rag_prompt(language: str, messages: List[object], sources: List[dict]) -> List[dict]:
    system = _compose_system_prompt(
        language,
        "Answer strictly and only using the provided SOURCES. "
        "If the answer is not in the SOURCES, say that the answer is not available in the internal documents and redirect to supported topics.",
    )
    sources_text = []
    for source in sources:
        label = f"{source['title']} — {source['section']} (version {source['version']})"
        sources_text.append(f"[{label}]\n{source['text']}")
    sources_block = "\n\n".join(sources_text)
    last_user = next((m for m in reversed(messages) if m.role == "user"), None)
    question = last_user.content if last_user else ""
    user = f"SOURCES:\n{sources_block}\n\nQUESTION:\n{question}"
    return _messages_to_input(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )


def _compose_system_prompt(language: str, extra: str) -> str:
    base = (load_system_prompt() or DEFAULT_SYSTEM_PROMPT).strip()
    if not base.endswith((".", "!", "?")):
        base = f"{base}."
    return f"{base} Reply in English. {extra}"


def _messages_to_input(messages: List[dict]) -> List[dict]:
    out: List[dict] = []
    for message in messages:
        out.append(
            {
                "role": message["role"],
                "content": [{"type": "input_text", "text": message["content"]}],
            }
        )
    return out
