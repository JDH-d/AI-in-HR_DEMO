from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from services.workflow_service import WorkflowService
from storage.chat_log_store import ChatLogStore
from storage.document_store import DocumentStore


class QualityService:
    def __init__(self, workflow: WorkflowService, logs: ChatLogStore, documents: DocumentStore):
        self.workflow = workflow
        self.logs = logs
        self.documents = documents

    def metrics(self) -> dict:
        return quality_metrics(self.workflow, self.logs, self.documents)

    def unanswered(self) -> list[dict]:
        return unanswered_entries(self.logs.read(1000), self.workflow.reviewed_quality_item_ids())

    def read_logs(self, limit: int) -> list[dict]:
        return self.logs.read(limit)


def quality_metrics(
    workflow: WorkflowService, chat_logs: ChatLogStore, documents: DocumentStore
) -> dict:
    metrics = workflow.metrics()
    logs = chat_logs.read(1000)
    workplace_logs = [entry for entry in logs if entry.get("intent") == "work"]
    question_count = len(workplace_logs)
    grounded_count = sum(1 for entry in workplace_logs if entry.get("sources"))
    unanswered = unanswered_entries(
        workplace_logs,
        workflow.reviewed_quality_item_ids(),
    )
    total_feedback = metrics["feedback"] + metrics["assistant_feedback"]
    metrics.update(
        {
            "documents": len(documents.list_documents()),
            "chat_logs": question_count,
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
    return metrics


def unanswered_entries(logs: list[dict], reviewed_ids: set[str] | None = None) -> list[dict]:
    unanswered: list[dict] = []
    reviewed = reviewed_ids or set()
    for entry in reversed(logs):
        assistant = str(entry.get("assistant", ""))
        if entry.get("intent") != "work":
            continue
        if entry.get("sources"):
            continue
        if "could not find a reliable answer" not in assistant:
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
