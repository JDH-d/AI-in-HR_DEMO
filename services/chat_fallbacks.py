from __future__ import annotations

from rag.topic_guidance import get_topic_examples


class ChatFallbackPolicy:
    def capabilities(self, language: str) -> str:
        return (
            "I can help with the following topics:\n"
            "1. PTO, vacation, and sick leave\n"
            "2. Salary and payroll\n"
            "3. Employee benefits\n"
            "4. Work schedules and shifts\n"
            "5. IT support, including VPN, access permissions, and password resets"
        )

    def small_talk(self, language: str) -> str:
        return "Hello. I can help with PTO and leave, payroll, benefits, schedules, or IT support."

    def topic_selection(self, language: str, topic: str) -> str:
        examples = self._format_topic_examples(topic)
        return (
            f"You selected {topic}. What would you like to know?\n"
            f"Examples:\n{examples}"
        )

    def topic_answer(self, language: str, topic: str, matched_text: str) -> str:
        cleaned = (matched_text or "").strip()
        if cleaned:
            return cleaned
        examples = self._format_topic_examples(topic)
        return (
            f"I can help with {topic}, but I need a more specific question.\n"
            f"Examples:\n{examples}"
        )

    def invalid(self, language: str) -> str:
        return (
            "I can assist only with supported workplace topics such as PTO and leave, payroll, "
            "benefits, work schedules, and IT support."
        )

    def no_docs(self, language: str) -> str:
        return "I could not find a reliable answer in the internal documents.\n" + self.capabilities(language)

    def service_unavailable(self, language: str) -> str:
        return (
            "The assistant service is temporarily unavailable. Please try again in 1 to 2 minutes.\n"
            + self.capabilities(language)
        )

    @staticmethod
    def workflow_created(request_id: str, status: str) -> str:
        return f"Request created successfully. ID: {request_id}; status: {status}."

    @staticmethod
    def _format_topic_examples(topic: str) -> str:
        return "\n".join(f"- {question}" for question in get_topic_examples(topic)[:3])
