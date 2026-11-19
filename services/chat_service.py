from __future__ import annotations

from dataclasses import replace

from domain.chat import ChatOutcome, ChatQuery
from domain.errors import ChatInputError
from integrations.llm_service import LLMService
from rag.nlp import Intent, contains_cyrillic
from services.workflow_service import WorkflowService
from storage.ai_settings_store import AI_SETTINGS_DEFAULTS, AISettingsStore
from storage.chat_log_store import ChatLogStore
from storage.prompt_store import PromptStore

from .chat_fallbacks import ChatFallbackPolicy
from .chat_router import ChatRouter
from .rag_service import RAGService


class ChatService:
    def __init__(
        self,
        workflow_service: WorkflowService,
        llm_service: LLMService,
        chat_log_store: ChatLogStore,
        router: ChatRouter | None = None,
        fallback_policy: ChatFallbackPolicy | None = None,
        rag_service: RAGService | None = None,
        ai_settings_store: AISettingsStore | None = None,
        prompt_store: PromptStore | None = None,
    ) -> None:
        self.workflow_service = workflow_service
        self.llm_service = llm_service
        self.chat_log_store = chat_log_store
        self.ai_settings_store = ai_settings_store
        self.fallback_policy = fallback_policy or ChatFallbackPolicy()
        self.router = router or ChatRouter()
        self.rag_service = rag_service or RAGService(
            llm_service=llm_service,
            fallback_policy=self.fallback_policy,
            ai_settings_store=ai_settings_store,
            prompt_store=prompt_store,
        )

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
            raise ChatInputError("The request must include at least one message.")

        latest_user = query.latest_user_message
        if latest_user is None:
            raise ChatInputError("The request must include at least one user message.")

        active_settings = settings or (
            self.ai_settings_store.get()
            if self.ai_settings_store is not None
            else dict(AI_SETTINGS_DEFAULTS)
        )
        decision = self.router.route(query)
        outcome = self._resolve_outcome(
            query,
            decision,
            created_by,
            settings=active_settings,
            system_prompt=system_prompt,
            allow_workflow=allow_workflow,
        )
        if log_outcome:
            self._log_outcome(latest_user.content, outcome)
        return (
            outcome if active_settings.get("show_sources", True) else replace(outcome, sources=[])
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
    ) -> ChatOutcome:
        latest_user = query.latest_user_message
        assert latest_user is not None

        if contains_cyrillic(latest_user.content):
            return ChatOutcome(
                content="This assistant supports English only. Please ask your question in English.",
                intent=Intent.INVALID,
                language="en",
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
                ),
                intent=Intent.WORK,
                language=decision.language,
                workflow_request=workflow_request,
            )

        if decision.intent == Intent.CAPABILITIES:
            return ChatOutcome(
                content=self.fallback_policy.capabilities(decision.language),
                intent=decision.intent,
                language=decision.language,
            )

        if decision.intent == Intent.SMALL_TALK:
            return ChatOutcome(
                content=self.fallback_policy.small_talk(decision.language),
                intent=decision.intent,
                language=decision.language,
            )

        if decision.topic_selection:
            return ChatOutcome(
                content=self.fallback_policy.topic_selection(
                    decision.language,
                    decision.topic_selection,
                ),
                intent=decision.intent,
                language=decision.language,
            )

        if (
            decision.intent == Intent.WORK
            and decision.prior_topic
            and self._is_underspecified_follow_up(latest_user.content)
        ):
            return ChatOutcome(
                content=self.fallback_policy.topic_answer(
                    decision.language,
                    decision.prior_topic,
                    "",
                ),
                intent=Intent.WORK,
                language=decision.language,
            )

        return self.rag_service.answer_with_retrieval(
            query,
            decision,
            settings=settings,
            system_prompt=system_prompt,
        )

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

    def _log_outcome(self, user_text: str, outcome: ChatOutcome) -> None:
        if outcome.intent == Intent.INVALID:
            return
        self.chat_log_store.append_chat(
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
        )
