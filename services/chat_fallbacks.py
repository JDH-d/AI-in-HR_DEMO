from __future__ import annotations

from rag.topic_guidance import get_topic_examples


class ChatFallbackPolicy:
    def capabilities(self) -> str:
        return (
            "I can help with the following topics:\n"
            "1. PTO, vacation, and sick leave\n"
            "2. Salary and payroll\n"
            "3. Employee benefits\n"
            "4. Work schedules and shifts\n"
            "5. IT support, including VPN, access permissions, and password resets"
        )

    def small_talk(self) -> str:
        return "Hello. I can help with PTO and leave, payroll, benefits, schedules, or IT support."

    def hr_support(self) -> str:
        return (
            "I’ve opened a private HR support request for you. An HR partner will review it "
            "and follow up here. You can add any helpful context in this conversation."
        )

    def topic_selection(self, topic: str) -> str:
        examples = self._format_topic_examples(topic)
        return f"You selected {topic}. What would you like to know?\nExamples:\n{examples}"

    def topic_answer(self, topic: str, matched_text: str) -> str:
        cleaned = (matched_text or "").strip()
        if cleaned:
            return cleaned
        examples = self._format_topic_examples(topic)
        return (
            f"I can help with {topic}, but I need a more specific question.\nExamples:\n{examples}"
        )

    def invalid(self) -> str:
        return (
            "I can assist only with supported workplace topics such as PTO and leave, payroll, "
            "benefits, work schedules, and IT support."
        )

    def no_docs(self) -> str:
        return (
            "I could not find a reliable answer in the internal documents.\n" + self.capabilities()
        )

    def service_unavailable(self) -> str:
        return (
            "The assistant service is temporarily unavailable. Please try again in 1 to 2 minutes.\n"
            + self.capabilities()
        )

    @staticmethod
    def workflow_draft(request_id: str, validation_errors: list[str]) -> str:
        message = (
            f"I prepared request draft {request_id}. "
            "Review the extracted fields and confirm before it is sent for review."
        )
        if validation_errors:
            message += " Please correct the highlighted fields before confirmation."
        return message

    @staticmethod
    def _format_topic_examples(topic: str) -> str:
        return "\n".join(f"- {question}" for question in get_topic_examples(topic)[:3])
