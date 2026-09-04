from __future__ import annotations

MAX_CONTEXT_MESSAGES = 8
MAX_CONTEXT_CHARS = 12_000

DEFAULT_SYSTEM_PROMPT = (
    "You are a professional internal knowledge and workflow assistant for a company demo. "
    "Use the configured company documents as the source of truth. "
    "Be concise, accurate, and businesslike. Do not invent policies or process details."
)


def build_rag_prompt(
    language: str,
    messages: list[object],
    sources: list[dict],
    system_prompt: str | None = None,
    settings: dict[str, bool] | None = None,
) -> list[dict]:
    strict = (settings or {}).get("strict_grounding", True)
    grounding_instruction = (
        "Answer strictly and only using the provided SOURCES. "
        "If the answer is not in the SOURCES, say that the answer is not available in the internal documents and redirect to supported topics."
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
    conversation = _recent_conversation(messages)
    for message in reversed(conversation):
        if message["role"] == "user":
            message["content"] = (
                f"SOURCES:\n{sources_block}\n\nCURRENT QUESTION:\n{message['content']}"
            )
            break
    return _messages_to_input([{"role": "system", "content": system}, *conversation])


def build_general_prompt(
    language: str,
    messages: list[object],
    system_prompt: str | None = None,
    settings: dict[str, bool] | None = None,
) -> list[dict]:
    system = _compose_system_prompt(
        language,
        "No internal source matched this question. Give general workplace guidance only, explicitly state that it is not confirmed company policy, and recommend checking with HR when policy-specific details matter.",
        base_prompt=system_prompt,
        settings=settings,
    )
    return _messages_to_input(
        [{"role": "system", "content": system}, *_recent_conversation(messages)]
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
    reply_language = "English" if language == "en" else language
    return f"{base} Reply in {reply_language}. {behavior} {extra}".strip()


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


def _messages_to_input(messages: list[dict]) -> list[dict]:
    out: list[dict] = []
    for message in messages:
        out.append(
            {
                "role": message["role"],
                "content": [{"type": "input_text", "text": message["content"]}],
            }
        )
    return out


def _recent_conversation(messages: list[object]) -> list[dict[str, str]]:
    conversation = [
        {"role": message.role, "content": str(message.content).strip()}
        for message in messages
        if getattr(message, "role", None) in {"user", "assistant"}
        and str(getattr(message, "content", "")).strip()
    ][-MAX_CONTEXT_MESSAGES:]
    while conversation and sum(len(item["content"]) for item in conversation) > MAX_CONTEXT_CHARS:
        conversation.pop(0)
    return conversation
