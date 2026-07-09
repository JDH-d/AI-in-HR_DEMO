from __future__ import annotations

from fastapi import HTTPException

from api.schemas import ChatRequest, ChatResponse, Message, SourceChunk
from rag.nlp import Intent
from rag.prompts import (
    build_capabilities_prompt,
    build_invalid_prompt,
    build_small_talk_prompt,
    build_topic_selection_prompt,
)
from workflow import WorkflowService

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
    ) -> None:
        self.workflow_service = workflow_service
        self.llm_service = llm_service
        self.log_service = log_service
        self.document_service = document_service
        self.fallback_policy = fallback_policy or ChatFallbackPolicy()
        self.router = router or ChatRouter(document_service)
        self.rag_service = rag_service or RAGService(
            llm_service=llm_service,
            document_service=document_service,
            fallback_policy=self.fallback_policy,
        )

    def handle_chat(self, req: ChatRequest, created_by: str) -> ChatResponse:
        query = ChatQuery(
            messages=[ChatTurn(role=message.role, content=message.content) for message in req.messages],
            top_k=req.top_k or 4,
            min_similarity=req.min_similarity or 0.25,
        )
        outcome = self.respond(query, created_by=created_by)
        return ChatResponse(
            message=Message(role="assistant", content=outcome.content),
            intent=outcome.intent.value,
            language=outcome.language,
            sources=[
                SourceChunk(
                    source=source.source,
                    chunk_id=source.chunk_id,
                    text=source.text,
                    score=source.score,
                )
                for source in outcome.sources
            ],
        )

    def respond(self, query: ChatQuery, created_by: str) -> ChatOutcome:
        if not query.messages:
            raise HTTPException(status_code=400, detail="The request must include at least one message.")

        latest_user = query.latest_user_message
        if latest_user is None:
            raise HTTPException(
                status_code=400,
                detail="The request must include at least one user message.",
            )

        decision = self.router.route(query)
        outcome = self._resolve_outcome(query, decision, created_by)
        self._log_outcome(latest_user.content, outcome)
        return outcome

    def _resolve_outcome(self, query: ChatQuery, decision, created_by: str) -> ChatOutcome:
        latest_user = query.latest_user_message
        assert latest_user is not None

        workflow_request = self.workflow_service.try_create(
            latest_user.content,
            created_by=created_by,
        )
        if workflow_request:
            return ChatOutcome(
                content=self.fallback_policy.workflow_created(
                    workflow_request["id"],
                    workflow_request["status"],
                ),
                intent=Intent.WORK,
                language=decision.language,
            )

        if (
            decision.intent == Intent.WORK
            and decision.prior_topic
            and not decision.explicit_topic_choice
        ):
            content = self.rag_service.answer_from_topic(
                decision.prior_topic,
                latest_user.content,
                decision.language,
            )
            if content:
                return ChatOutcome(
                    content=content,
                    intent=decision.intent,
                    language=decision.language,
                )

        if decision.intent == Intent.CAPABILITIES:
            content = self.rag_service.generate_with_fallback(
                build_capabilities_prompt(decision.language, query.messages),
                self.fallback_policy.capabilities(decision.language),
            )
            return ChatOutcome(content=content, intent=decision.intent, language=decision.language)

        if decision.intent == Intent.SMALL_TALK:
            content = self.rag_service.generate_with_fallback(
                build_small_talk_prompt(decision.language, query.messages),
                self.fallback_policy.small_talk(decision.language),
            )
            return ChatOutcome(content=content, intent=decision.intent, language=decision.language)

        if decision.topic_selection:
            content = self.rag_service.generate_with_fallback(
                build_topic_selection_prompt(decision.language, decision.topic_selection),
                self.fallback_policy.topic_selection(decision.language, decision.topic_selection),
            )
            return ChatOutcome(content=content, intent=decision.intent, language=decision.language)

        if decision.intent == Intent.INVALID:
            content = self.rag_service.generate_with_fallback(
                build_invalid_prompt(decision.language, query.messages),
                self.fallback_policy.invalid(decision.language),
            )
            return ChatOutcome(content=content, intent=decision.intent, language=decision.language)

        return self.rag_service.answer_with_retrieval(query, decision)

    def _log_outcome(self, user_text: str, outcome: ChatOutcome) -> None:
        self.log_service.append_chat(
            user_text=user_text,
            assistant_text=outcome.content,
            intent=outcome.intent.value,
            language=outcome.language,
            sources=[
                {"source": source.source, "chunk_id": source.chunk_id, "score": source.score}
                for source in outcome.sources
            ]
            if outcome.sources is not None
            else None,
        )
