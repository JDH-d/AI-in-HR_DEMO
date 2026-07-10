from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from api.schemas import ChatRequest


class LoginRequest(BaseModel):
    username: Literal["employee", "manager", "knowledge_admin"]
    password: str = Field(..., min_length=1)


class StructuredRequestCreate(BaseModel):
    type: Literal["pto", "sick_leave", "document"]
    start_date: str | None = None
    end_date: str | None = None
    comment: str = Field(..., min_length=1)
    approver: str | None = None


class RequestSubmit(BaseModel):
    type: Literal["pto", "sick_leave", "document"] | None = None
    start_date: str | None = None
    end_date: str | None = None
    comment: str | None = None
    approver: str | None = None


class DecisionRequest(BaseModel):
    comment: str = ""


class FeedbackCreate(BaseModel):
    request_id: str | None = None
    rating: int = Field(..., ge=1, le=5)
    comment: str = ""
    question: str = ""
    answer: str = ""


class AISettingsPayload(BaseModel):
    strict_grounding: bool = True
    concise_answers: bool = True
    ask_clarifying_questions: bool = True
    suggest_next_steps: bool = True
    show_sources: bool = True
    auto_index_uploads: bool = True


class AISettingsUpdate(BaseModel):
    settings: AISettingsPayload
    system_prompt: str = Field(..., min_length=1)

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("System prompt cannot be empty.")
        return cleaned


class AISettingsTestRequest(AISettingsUpdate):
    question: str = Field(..., min_length=1)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Test question cannot be empty.")
        return cleaned


class QualityReviewAction(BaseModel):
    action: Literal["resolved", "ignored"]


class V1ChatRequest(ChatRequest):
    pass
