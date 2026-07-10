from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

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


class V1ChatRequest(ChatRequest):
    pass
