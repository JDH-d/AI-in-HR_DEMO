from __future__ import annotations

from typing import List, Optional

from openai import OpenAI, OpenAIError


class LLMServiceError(RuntimeError):
    pass


class LLMService:
    def __init__(self, primary_model: str, fallback_model: str) -> None:
        self.primary_model = primary_model
        self.fallback_model = fallback_model
        self.client: Optional[OpenAI] = None

    def generate(self, prompt_messages: List[dict]) -> str:
        client = self._get_client()
        try:
            if hasattr(client, "responses"):
                resp = client.responses.create(
                    model=self.primary_model,
                    input=prompt_messages,
                    max_output_tokens=512,
                )
                if getattr(resp, "output_text", None):
                    return resp.output_text.strip()

                text_parts: List[str] = []
                for item in getattr(resp, "output", []) or []:
                    item_type = getattr(item, "type", None) or (
                        item.get("type") if isinstance(item, dict) else None
                    )
                    if item_type != "message":
                        continue
                    item_content = getattr(item, "content", None) or (
                        item.get("content") if isinstance(item, dict) else None
                    )
                    if not item_content:
                        continue
                    for part in item_content:
                        if isinstance(part, dict):
                            if part.get("type") in {"output_text", "text"} and part.get("text"):
                                text_parts.append(part["text"])
                            elif part.get("text"):
                                text_parts.append(part["text"])
                        else:
                            part_type = getattr(part, "type", None)
                            part_text = getattr(part, "text", None)
                            if part_type in {"output_text", "text"} and part_text:
                                text_parts.append(part_text)
                text = "".join(text_parts).strip()
                if text:
                    return text

            legacy_messages: List[dict] = []
            for message in prompt_messages:
                content = message.get("content", "")
                if isinstance(content, list) and content:
                    first = content[0]
                    if isinstance(first, dict) and first.get("type") == "input_text":
                        content = first.get("text", "")
                legacy_messages.append(
                    {"role": message.get("role", "user"), "content": content}
                )

            resp = client.chat.completions.create(
                model=self.fallback_model,
                messages=legacy_messages,
                max_completion_tokens=512,
            )
            return (resp.choices[0].message.content or "").strip()
        except (
            AttributeError,
            IndexError,
            KeyError,
            OpenAIError,
            TypeError,
            ValueError,
        ) as exc:
            raise LLMServiceError("LLM generation failed") from exc

    def _get_client(self) -> OpenAI:
        if self.client is not None:
            return self.client
        try:
            self.client = OpenAI()
        except (OpenAIError, OSError, TypeError, ValueError) as exc:
            raise LLMServiceError("OpenAI client is not configured") from exc
        return self.client
