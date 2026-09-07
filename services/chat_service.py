from __future__ import annotations

import re
from collections.abc import Iterator

from rag.index import KnowledgeIndex
from rag.nlp import Intent
from workflow import WorkflowService

from .ai_settings_service import AI_SETTINGS_DEFAULTS, AISettingsService
from .chat_fallbacks import ChatFallbackPolicy
from .chat_models import ChatOutcome, ChatQuery, ChatStreamUpdate
from .chat_router import ChatRouter
from .llm_service import LLMService, LLMServiceError
from .log_service import ChatLogService
from .rag_service import PreparedRAGAnswer, RAGService


class ChatValidationError(ValueError):
    pass


class ChatService:
    def __init__(
        self,
        workflow_service: WorkflowService,
        llm_service: LLMService,
        log_service: ChatLogService,
        router: ChatRouter | None = None,
        fallback_policy: ChatFallbackPolicy | None = None,
        rag_service: RAGService | None = None,
        ai_settings_service: AISettingsService | None = None,
        knowledge_index: KnowledgeIndex | None = None,
    ) -> None:
        self.workflow_service = workflow_service
        self.llm_service = llm_service
        self.log_service = log_service
        self.ai_settings_service = ai_settings_service
        self.fallback_policy = fallback_policy or ChatFallbackPolicy()
        self.router = router or ChatRouter()
        if rag_service is None:
            if knowledge_index is None:
                raise ValueError("knowledge_index is required when rag_service is not provided")
            rag_service = RAGService(
                llm_service=llm_service,
                fallback_policy=self.fallback_policy,
                ai_settings_service=ai_settings_service,
                knowledge_index=knowledge_index,
            )
        self.rag_service = rag_service

    def respond(
        self,
        query: ChatQuery,
        created_by: str,
        *,
        settings: dict[str, bool] | None = None,
        system_prompt: str | None = None,
        log_outcome: bool = True,
        allow_workflow: bool = True,
    ) -> ChatOutcome:
        if not query.messages:
            raise ChatValidationError("The request must include at least one message.")

        latest_user = query.latest_user_message
        if latest_user is None:
            raise ChatValidationError("The request must include at least one user message.")

        active_settings, active_system_prompt = self._resolve_configuration(
            settings,
            system_prompt,
        )
        prepared = self._resolve_outcome(
            query,
            self.router.route(query),
            created_by,
            settings=active_settings,
            system_prompt=active_system_prompt,
            allow_workflow=allow_workflow,
        )
        outcome = (
            prepared
            if isinstance(prepared, ChatOutcome)
            else prepared.complete(
                self.rag_service.generate_with_fallback(
                    prepared.prompt_messages,
                    prepared.fallback_text,
                )
            )
        )
        if log_outcome:
            self._log_outcome(latest_user.content, outcome)
        return outcome

    def stream(
        self,
        query: ChatQuery,
        created_by: str,
        *,
        settings: dict[str, bool] | None = None,
        system_prompt: str | None = None,
        log_outcome: bool = True,
        allow_workflow: bool = True,
    ) -> Iterator[ChatStreamUpdate]:
        if not query.messages:
            raise ChatValidationError("The request must include at least one message.")
        latest_user = query.latest_user_message
        if latest_user is None:
            raise ChatValidationError("The request must include at least one user message.")

        active_settings, active_system_prompt = self._resolve_configuration(
            settings,
            system_prompt,
        )
        prepared = self._resolve_outcome(
            query,
            self.router.route(query),
            created_by,
            settings=active_settings,
            system_prompt=active_system_prompt,
            allow_workflow=allow_workflow,
        )
        workflow_request = prepared.workflow_request if isinstance(prepared, ChatOutcome) else None
        stream_completed = False
        try:
            if isinstance(prepared, ChatOutcome):
                yield ChatStreamUpdate(kind="token", content=prepared.content)
                outcome = prepared
            else:
                tokens: list[str] = []
                try:
                    for token in self.llm_service.stream_generate(prepared.prompt_messages):
                        tokens.append(token)
                        yield ChatStreamUpdate(kind="token", content=token)
                    content = "".join(tokens).strip()
                    if not content:
                        content = prepared.fallback_text
                        yield ChatStreamUpdate(
                            kind="replace" if tokens else "token",
                            content=content,
                        )
                except LLMServiceError:
                    content = prepared.fallback_text
                    yield ChatStreamUpdate(
                        kind="replace" if tokens else "token",
                        content=content,
                    )
                outcome = prepared.complete(content)

            if log_outcome:
                self._log_outcome(latest_user.content, outcome)
            stream_completed = True
            yield ChatStreamUpdate(kind="complete", outcome=outcome)
        finally:
            if not stream_completed and workflow_request:
                self.workflow_service.discard_unshared_draft(
                    workflow_request["id"],
                    created_by,
                )

    def _resolve_outcome(
        self,
        query: ChatQuery,
        decision,
        created_by: str,
        *,
        settings: dict[str, bool] | None,
        system_prompt: str | None,
        allow_workflow: bool,
    ) -> ChatOutcome | PreparedRAGAnswer:
        latest_user = query.latest_user_message
        assert latest_user is not None

        if self._is_hr_support_request(latest_user.content):
            return ChatOutcome(
                content=self.fallback_policy.hr_support(),
                intent=Intent.WORK,
                language=decision.language,
                outcome_code="handoff_demo",
            )

        workflow_request = (
            self.workflow_service.prepare_draft(
                latest_user.content,
                applicant=created_by,
            )
            if allow_workflow
            else None
        )
        if workflow_request:
            return ChatOutcome(
                content=self.fallback_policy.workflow_draft(
                    workflow_request["id"],
                    workflow_request.get("validation_errors", []),
                    request_type=workflow_request["type"],
                ),
                intent=Intent.WORK,
                language=decision.language,
                workflow_request=workflow_request,
                outcome_code="workflow",
            )

        request_help_type = self._request_help_type(latest_user.content)
        if request_help_type:
            return ChatOutcome(
                content=self.fallback_policy.request_guidance(request_help_type),
                intent=Intent.WORK,
                language=decision.language,
                outcome_code="guided",
            )

        if decision.intent == Intent.CAPABILITIES:
            return ChatOutcome(
                content=self.fallback_policy.capabilities(),
                intent=decision.intent,
                language=decision.language,
                outcome_code="guided",
            )

        if decision.intent == Intent.SMALL_TALK:
            return ChatOutcome(
                content=self.fallback_policy.small_talk(),
                intent=decision.intent,
                language=decision.language,
                outcome_code="guided",
            )

        if decision.topic_selection:
            return ChatOutcome(
                content=self.fallback_policy.topic_selection(
                    decision.topic_selection,
                ),
                intent=decision.intent,
                language=decision.language,
                outcome_code="guided",
            )

        if (
            decision.intent == Intent.WORK
            and decision.prior_topic
            and self._is_underspecified_follow_up(latest_user.content)
        ):
            return ChatOutcome(
                content=self.fallback_policy.topic_answer(
                    decision.prior_topic,
                    "",
                ),
                intent=Intent.WORK,
                language=decision.language,
                outcome_code="guided",
            )

        return self.rag_service.prepare_answer(
            query,
            decision,
            settings=settings,
            system_prompt=system_prompt,
        )

    def _resolve_configuration(
        self,
        settings: dict[str, bool] | None,
        system_prompt: str | None,
    ) -> tuple[dict[str, bool], str | None]:
        if settings is not None and system_prompt is not None:
            return settings, system_prompt
        if self.ai_settings_service is None:
            return settings or dict(AI_SETTINGS_DEFAULTS), system_prompt

        configuration = self.ai_settings_service.get_configuration()
        return (
            settings if settings is not None else configuration["settings"],
            system_prompt if system_prompt is not None else configuration["system_prompt"],
        )

    @staticmethod
    def _request_help_type(text: str) -> str | None:
        """Answer app usage questions without substituting for company policy questions."""
        normalized = " ".join((text or "").lower().split()).strip(" ?.!")
        match = re.fullmatch(
            r"(?:how (?:can|do|should) i|what(?:'s| is) the (?:process|way) "
            r"(?:to|for)) (?:request(?:ing)?|apply(?:ing)? for|book(?:ing)?|report(?:ing)?|take) "
            r"(?:my |some |a )?(?P<type>pto|paid time off|time off|vacation|annual leave|"
            r"sick leave|sick day)(?: here| in slack| with you)?",
            normalized,
        )
        if not match:
            return None
        return "sick_leave" if match["type"].startswith("sick") else "pto"

    @staticmethod
    def _is_underspecified_follow_up(text: str) -> bool:
        normalized = " ".join((text or "").lower().split()).strip(" ?.!")
        return normalized in {
            "can you explain",
            "could you explain",
            "tell me more",
            "what about that",
            "how does that work",
            "can you elaborate",
        }

    @staticmethod
    def _is_hr_support_request(text: str) -> bool:
        normalized = " ".join((text or "").lower().split()).strip(" ?.!")
        return normalized in {
            "ask hr",
            "contact hr",
            "i need help from hr",
            "i need to speak with hr",
            "i want to talk to hr",
        }

    def _log_outcome(self, user_text: str, outcome: ChatOutcome) -> None:
        if outcome.intent == Intent.INVALID:
            return
        self.log_service.append_chat(
            user_text=user_text,
            assistant_text=outcome.content,
            intent=outcome.intent.value,
            language=outcome.language,
            sources=[
                {
                    "source": source.source,
                    "title": source.title,
                    "section": source.section,
                    "score": source.score,
                }
                for source in outcome.sources
            ]
            if outcome.sources is not None
            else None,
            outcome_code=outcome.outcome_code,
        )
