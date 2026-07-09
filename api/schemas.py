from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str = Field(..., description="user|assistant|system")
    content: str


class ChatRequest(BaseModel):
    messages: List[Message]
    top_k: Optional[int] = Field(4, ge=1, le=10)
    min_similarity: Optional[float] = Field(0.25, ge=0.0, le=1.0)


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
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    duration_days: Optional[int] = None
    comment: str
    applicant: str
    approver: str
    status: str
    created_at: str
    updated_at: str
    validation_errors: List[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    message: Message
    intent: str
    language: str
    sources: Optional[List[SourceChunk]] = None
    workflow_request: Optional[WorkflowRequestView] = None


class SystemPromptUpdate(BaseModel):
    system_prompt: str = Field(..., min_length=1)


class WorkflowStatusUpdate(BaseModel):
    status: str = Field(..., min_length=1)
    comment: str = ""


class WorkflowConfirmation(BaseModel):
    type: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    comment: Optional[str] = None
    approver: Optional[str] = None


class WorkflowAction(BaseModel):
    comment: str = ""


class WorkflowCommentCreate(BaseModel):
    body: str = Field(..., min_length=1)
    author: str = "Manager"


class WorkflowFeedbackCreate(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str = ""


class WorkflowEventView(BaseModel):
    id: str
    request_id: str
    event_type: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    actor: str
    details: dict[str, Any]
    created_at: str
