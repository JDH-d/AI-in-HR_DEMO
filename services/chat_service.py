from __future__ import annotations

from fastapi import HTTPException

from api.schemas import ChatRequest, ChatResponse, Message, SourceChunk
from rag.nlp import Intent
from workflow import WorkflowService

from .ai_settings_service import AI_SETTINGS_DEFAULTS, AISettingsService
from .chat_fallbacks import ChatFallbackPolicy
from .chat_models import ChatOutcome, ChatQuery, ChatTurn
from .chat_router import ChatRouter
from .document_service import DocumentService
from .llm_service import LLMService
from .log_service import ChatLogService
from .rag_service import RAGService


class ChatService:
    def __init__(
        self,
        workflow_service: WorkflowService,
        llm_service: LLMService,
        log_service: ChatLogService,
        document_service: DocumentService,
        router: ChatRouter | None = None,
        fallback_policy: ChatFallbackPolicy | None = None,
        rag_service: RAGService | None = None,
        ai_settings_service: AISettingsService | None = None,
    ) -> None:
        self.workflow_service = workflow_service
        self.llm_service = llm_service
        self.log_service = log_service
        self.document_service = document_service
        self.ai_settings_service = ai_settings_service
        self.fallback_policy = fallback_policy or ChatFallbackPolicy()
        self.router = router or ChatRouter(document_service)
        self.rag_service = rag_service or RAGService(
            llm_service=llm_service,
            document_service=document_service,
            fallback_policy=self.fallback_policy,
            ai_settings_service=ai_settings_service,
        )

    def handle_chat(
        self,
        req: ChatRequest,
        created_by: str,
        *,
        settings_override: dict[str, bool] | None = None,
        system_prompt_override: str | None = None,
        log_outcome: bool = True,
        allow_workflow: bool = True,
    ) -> ChatResponse:
        active_settings = settings_override or (
            self.ai_settings_service.get()
            if self.ai_settings_service is not None
            else dict(AI_SETTINGS_DEFAULTS)
        )
        query = ChatQuery(
            messages=[
                ChatTurn(role=message.role, content=message.content) for message in req.messages
            ],
            top_k=req.top_k or 4,
            min_similarity=req.min_similarity or 0.25,
        )
        outcome = self.respond(
            query,
            created_by=created_by,
            settings=active_settings,
            system_prompt=system_prompt_override,
            log_outcome=log_outcome,
            allow_workflow=allow_workflow,
        )
        return ChatResponse(
            message=Message(role="assistant", content=outcome.content),
            intent=outcome.intent.value,
            language=outcome.language,
            sources=[
                SourceChunk(
                    source=source.source,
                    title=source.title,
                    section=source.section,
                    category=source.category,
                    version=source.version,
                    excerpt=source.excerpt,
                    score=source.score,
                )
                for source in outcome.sources
            ]
            if active_settings.get("show_sources", True)
            else [],
            workflow_request=outcome.workflow_request,
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
            raise HTTPException(
                status_code=400, detail="The request must include at least one message."
            )

        latest_user = query.latest_user_message
        if latest_user is None:
            raise HTTPException(
                status_code=400,
                detail="The request must include at least one user message.",
            )

        decision = self.router.route(query)
        outcome = self._resolve_outcome(
            query,
            decision,
            created_by,
            settings=settings,
            system_prompt=system_prompt,
            allow_workflow=allow_workflow,
        )
        if log_outcome:
            self._log_outcome(latest_user.content, outcome)
        return outcome

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

        if self._is_hr_support_request(latest_user.content):
            return ChatOutcome(
                content=self.fallback_policy.hr_support(decision.language),
                intent=Intent.WORK,
                language=decision.language,
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
        )
