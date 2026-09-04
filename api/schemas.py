from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    messages: list[Message]
    top_k: int | None = Field(4, ge=1, le=10)
    min_similarity: float | None = Field(0.25, ge=0.0, le=1.0)


class SourceChunk(BaseModel):
    source: str
    title: str
    section: str
    category: str
    version: str
    excerpt: str
    score: float


class WorkflowRequestView(BaseModel):
    id: str
    type: str
    type_label: str
    start_date: str | None = None
    end_date: str | None = None
    duration_days: int | None = None
    comment: str
    applicant: str
    approver: str
    details: dict[str, object] = Field(default_factory=dict)
    status: str
    created_at: str
    updated_at: str
    validation_errors: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    message: Message
    intent: str
    language: str
    outcome_code: str
    sources: list[SourceChunk] | None = None
    workflow_request: WorkflowRequestView | None = None
    conversation_id: str | None = None


class WorkflowCommentCreate(BaseModel):
    body: str = Field(..., min_length=1)
