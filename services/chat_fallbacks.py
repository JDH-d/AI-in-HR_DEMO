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
            "Contacting HR is a simulated interaction in this demo. No HR ticket has been sent. "
            "I can help with company policies, time off, and sick leave."
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
    def workflow_draft(
        request_id: str,
        validation_errors: list[str],
        *,
        request_type: str = "pto",
    ) -> str:
        message = (
            "I've prepared a sick leave draft. Review your availability before sharing it "
            "with your manager."
            if request_type == "sick_leave"
            else "I've prepared a PTO draft. Review the dates and planning note before "
            "sending it to your manager."
        )
        if validation_errors:
            message += " Complete the missing or highlighted fields in the draft first."
        return message

    @staticmethod
    def request_guidance(request_type: str) -> str:
        if request_type == "sick_leave":
            return (
                'Tell me when you will be away, for example: "I need sick leave today." '
                "I'll prepare a draft where you can check your time away and expected return. "
                "Medical details aren't needed. Your manager is notified only after you review "
                "and send it."
            )
        return (
            "Tell me your start and end dates and a short planning note. "
            'For example: "I need PTO from YYYY-MM-DD to YYYY-MM-DD for a family trip." '
            "I'll prepare a draft for you to review. It goes to your manager only when you send it."
        )

    @staticmethod
    def _format_topic_examples(topic: str) -> str:
        return "\n".join(f"- {question}" for question in get_topic_examples(topic)[:3])
