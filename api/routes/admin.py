from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from api.chat_execution import execute_chat
from api.v1_dependencies import Services, require_roles
from api.v1_schemas import (
    AISettingsTestRequest,
    AISettingsUpdate,
    FeedbackCreate,
    QualityReviewAction,
    V1ChatRequest,
)
from services.auth_service import DemoIdentity
from workflow import WorkflowNotFoundError, WorkflowValidationError

router = APIRouter(prefix="/api/v1", tags=["admin"])


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
def add_feedback(
    payload: FeedbackCreate,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("employee")),
) -> dict:
    try:
        if payload.request_id:
            feedback = services.workflow.add_feedback(
                payload.request_id,
                identity.id,
                payload.rating,
                payload.comment,
            )
        else:
            feedback = services.workflow.add_assistant_feedback(
                payload.rating,
                payload.comment,
                payload.question,
                payload.answer,
            )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"feedback": feedback}


@router.get("/admin/feedback")
def admin_feedback(
    services: Services,
    sentiment: str = "all",
    limit: int = 200,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    try:
        items = services.workflow.list_assistant_feedback(sentiment=sentiment, limit=limit)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    return {"feedback": items}


@router.get("/admin/metrics")
def admin_metrics(
    services: Services,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    metrics = services.workflow.metrics()
    logs = services.logs.read()
    conversation_metrics = services.conversations.metrics()
    question_count = conversation_metrics["questions"]
    grounded_count = conversation_metrics["grounded_answers"]
    unanswered = build_unanswered_entries(
        logs,
        services.workflow.reviewed_quality_item_ids(),
    )
    total_feedback = metrics["feedback"] + metrics["assistant_feedback"]
    metrics.update(
        {
            "documents": len(services.documents.list_documents()),
            "questions": question_count,
            "grounded_answers": grounded_count,
            "grounded_answer_rate": round(
                (grounded_count / question_count * 100) if question_count else 0.0,
                1,
            ),
            "unanswered_questions": len(unanswered),
            "positive_feedback_rate": round(
                (metrics["positive_feedback"] / total_feedback * 100) if total_feedback else 0.0,
                1,
            ),
            "requests_created": metrics["total_requests"],
            "requests_approved": metrics["requests_by_status"].get("approved", 0),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return {"metrics": metrics}


@router.get("/admin/unanswered")
def unanswered_questions(
    services: Services,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    reviewed = services.workflow.reviewed_quality_item_ids()
    return {"questions": build_unanswered_entries(services.logs.read(), reviewed)}


@router.post("/admin/quality/{item_id}")
def review_quality_item(
    item_id: str,
    payload: QualityReviewAction,
    services: Services,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    try:
        review = services.workflow.review_quality_item(item_id, payload.action)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors) from exc
    return {"review": review}


@router.get("/admin/ai-settings")
def get_ai_settings(
    services: Services,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    return services.ai_settings.get_configuration()


@router.put("/admin/ai-settings")
def update_ai_settings(
    payload: AISettingsUpdate,
    services: Services,
    _: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    return services.ai_settings.save_configuration(
        payload.settings.model_dump(),
        payload.system_prompt,
    )


@router.post("/admin/ai-settings/test")
def test_ai_settings(
    payload: AISettingsTestRequest,
    services: Services,
    identity: DemoIdentity = Depends(require_roles("knowledge_admin")),
) -> dict:
    started = time.perf_counter()
    response = execute_chat(
        V1ChatRequest(messages=[{"role": "user", "content": payload.question}]),
        identity.id,
        services,
        settings_override=payload.settings.model_dump(),
        system_prompt_override=payload.system_prompt,
        log_outcome=False,
        allow_workflow=False,
    )
    return {
        "answer": response.message.content,
        "intent": response.intent,
        "sources": [source.model_dump() for source in response.sources or []],
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }


def build_unanswered_entries(logs: list[dict], reviewed_ids: set[str] | None = None) -> list[dict]:
    unanswered: list[dict] = []
    reviewed = reviewed_ids or set()
    for entry in reversed(logs):
        assistant = str(entry.get("assistant", ""))
        if entry.get("intent") != "work":
            continue
        if entry.get("sources"):
            continue
        outcome_code = entry.get("outcome_code")
        is_legacy_no_match = (
            outcome_code is None and "could not find a reliable answer" in assistant
        )
        if outcome_code != "no_match" and not is_legacy_no_match:
            continue
        question = str(entry.get("user", "Question text was not retained"))
        item_id = hashlib.sha256(f"{entry.get('ts', '')}\n{question}".encode("utf-8")).hexdigest()[
            :16
        ]
        if item_id in reviewed:
            continue
        unanswered.append(
            {
                "id": item_id,
                "timestamp": entry.get("ts"),
                "question": question,
                "assistant": assistant,
            }
        )
    return unanswered[:50]
