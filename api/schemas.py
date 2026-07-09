from __future__ import annotations

from typing import List, Optional

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
    chunk_id: int
    text: str
    score: float


class ChatResponse(BaseModel):
    message: Message
    intent: str
    language: str
    sources: Optional[List[SourceChunk]] = None


class SystemPromptUpdate(BaseModel):
    system_prompt: str = Field(..., min_length=1)


class WorkflowStatusUpdate(BaseModel):
    status: str = Field(..., min_length=1)

