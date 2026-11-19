from __future__ import annotations

from typing import List

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional internal knowledge and workflow assistant for a company demo. "
    "Use the configured company documents as the source of truth. "
    "Be concise, accurate, and businesslike. Do not invent policies or process details."
)


def build_rag_prompt(
    language: str,
    messages: List[object],
    sources: List[dict],
    system_prompt: str | None = None,
    settings: dict[str, bool] | None = None,
) -> List[dict]:
    strict = (settings or {}).get("strict_grounding", True)
    grounding_instruction = (
        "Base company policy and process claims strictly on the provided SOURCES. "
        "If a policy answer is not in the SOURCES, say that it is not available in the internal documents and redirect to supported topics."
        if strict
        else "Treat the provided SOURCES as authoritative. You may add clearly identified general workplace guidance when the sources do not fully answer the question."
    )
    system = _compose_system_prompt(
        language,
        grounding_instruction,
        base_prompt=system_prompt,
        settings=settings,
    )
    sources_text = []
    for source in sources:
        label = f"{source['title']} — {source['section']} (version {source['version']})"
        sources_text.append(f"[{label}]\n{source['text']}")
    sources_block = "\n\n".join(sources_text)
    last_user = next((m for m in reversed(messages) if m.role == "user"), None)
    question = last_user.content if last_user else ""
    user = f"SOURCES:\n{sources_block}\n\nQUESTION:\n{question}"
    return _conversation_input(system, messages, user)


def build_general_prompt(
    language: str,
    messages: List[object],
    system_prompt: str | None = None,
    settings: dict[str, bool] | None = None,
) -> List[dict]:
    system = _compose_system_prompt(
        language,
        "No internal source matched this question. Give general workplace guidance only, explicitly state that it is not confirmed company policy, and recommend checking with HR when policy-specific details matter.",
        base_prompt=system_prompt,
        settings=settings,
    )
    last_user = next((message for message in reversed(messages) if message.role == "user"), None)
    question = last_user.content if last_user else ""
    return _conversation_input(system, messages, question)


def _conversation_input(system: str, messages: List[object], latest_content: str) -> List[dict]:
    last_user_index = next(
        (index for index in range(len(messages) - 1, -1, -1) if messages[index].role == "user"),
        0,
    )
    # Prior turns come from the authorised conversation, not client-supplied system roles.
    history = [
        {"role": message.role, "content": message.content}
        for message in messages[:last_user_index]
        if message.role in {"user", "assistant"}
    ]
    return _messages_to_input(
        [
            {"role": "system", "content": system},
            *history,
            {"role": "user", "content": latest_content},
        ]
    )


def _compose_system_prompt(
    language: str,
    extra: str,
    base_prompt: str | None = None,
    settings: dict[str, bool] | None = None,
) -> str:
    base = (base_prompt or DEFAULT_SYSTEM_PROMPT).strip()
    if not base.endswith((".", "!", "?")):
        base = f"{base}."
    behavior = _behavior_instructions(settings or {})
    context = (
        "Use the conversation history to resolve references and recall user-provided details. "
        "Earlier assistant replies are not authoritative company policy; verify policy claims against the current sources. "
        "Address every question in the latest message, using separate short points when needed. "
        "For a follow-up, answer the new condition or detail rather than simply repeating the previous answer. "
        "If only part of a question is supported, answer that part and identify exactly what information is missing."
    )
    return f"{base} Reply in English. {behavior} {extra} {context}".strip()


def _behavior_instructions(settings: dict[str, bool]) -> str:
    instructions: list[str] = []
    if settings.get("concise_answers", True):
        instructions.append("Keep the answer concise and easy to scan.")
    else:
        instructions.append("Give a complete explanation with enough operational context.")
    if settings.get("ask_clarifying_questions", True):
        instructions.append("When the request is ambiguous, ask one focused clarifying question.")
    if settings.get("suggest_next_steps", True):
        instructions.append("When useful, end with one practical next step.")
    return " ".join(instructions)


def _messages_to_input(messages: List[dict]) -> List[dict]:
    out: List[dict] = []
    for message in messages:
        out.append(
            {
                "role": message["role"],
                "content": message["content"]
                if message["role"] == "assistant"
                else [{"type": "input_text", "text": message["content"]}],
            }
        )
    return out
