from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from core.settings import SYSTEM_PROMPT_PATH
from rag.topic_guidance import get_topic_examples


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


def build_capabilities_prompt(language: str, messages: List[object]) -> List[dict]:
    system = _compose_system_prompt(
        language,
        "Return a concise, well-structured list of supported topics and nothing else.",
    )
    user = (
        "List only the following supported topics:\n"
        "1. PTO, vacation, and sick leave\n"
        "2. Salary and payroll\n"
        "3. Employee benefits\n"
        "4. Work schedules and shifts\n"
        "5. IT support (VPN, access permissions, password reset)"
    )
    return _messages_to_input(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )


def build_small_talk_prompt(language: str, messages: List[object]) -> List[dict]:
    system = _compose_system_prompt(
        language,
        "Respond briefly and politely to casual greetings, then redirect to "
        "a supported work-related topic. Keep it under 2 sentences.",
    )
    user = (
        "Reply briefly and then redirect to these topics: "
        "PTO/vacation/sick leave, salary/payroll, benefits, schedules/shifts, "
        "IT support (VPN, access permissions, password reset)."
    )
    return _messages_to_input(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )


def build_invalid_prompt(
    language: str, messages: List[object], reason: Optional[str] = None
) -> List[dict]:
    reason_text = ""
    if reason == "no_relevant_docs":
        reason_text = "No relevant internal documents were found. "
    system = _compose_system_prompt(
        language,
        f"{reason_text}Politely decline unsupported requests and redirect to supported work-related topics.",
    )
    user = (
        "Refuse and redirect to these topics: "
        "PTO/vacation/sick leave, salary/payroll, benefits, schedules/shifts, "
        "IT support (VPN, access permissions, password reset)."
    )
    return _messages_to_input(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )


def build_rag_prompt(language: str, messages: List[object], sources: List[dict]) -> List[dict]:
    system = _compose_system_prompt(
        language,
        "Answer strictly and only using the provided SOURCES. "
        "If the answer is not in the SOURCES, say that the answer is not available in the internal documents and redirect to supported topics.",
    )
    sources_text = []
    for source in sources:
        sources_text.append(f"[{source['source']}#{source['chunk_id']}]\n{source['text']}")
    sources_block = "\n\n".join(sources_text)
    last_user = next((m for m in reversed(messages) if m.role == "user"), None)
    question = last_user.content if last_user else ""
    user = f"SOURCES:\n{sources_block}\n\nQUESTION:\n{question}"
    return _messages_to_input(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )


def build_topic_selection_prompt(language: str, topic: str) -> List[dict]:
    examples = get_topic_examples(topic)
    examples_block = "\n".join(f"- {question}" for question in examples[:3])
    system = _compose_system_prompt(
        language,
        "Acknowledge the selected topic and ask a concise follow-up question to proceed in a professional tone.",
    )
    user = (
        f"The user selected this topic: {topic}. "
        "Reply briefly, ask what they want to know about it, and include 2 to 3 short example follow-up questions.\n"
        f"Example questions:\n{examples_block}"
    )
    return _messages_to_input(
        [{"role": "system", "content": system}, {"role": "user", "content": user}]
    )


def build_topic_answer_prompt(
    language: str,
    topic: str,
    question: str,
    topic_source: str,
) -> List[dict]:
    system = _compose_system_prompt(
        language,
        "The user already selected a supported topic. Answer only using TOPIC_SOURCE. "
        "Keep the answer concise and directly responsive to the question. "
        "Do not restate or dump the full document. "
        "If the answer is not available in TOPIC_SOURCE, say that clearly and invite a more specific follow-up question.",
    )
    user = (
        f"TOPIC:\n{topic}\n\n"
        f"TOPIC_SOURCE:\n{topic_source}\n\n"
        f"QUESTION:\n{question}"
    )
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
