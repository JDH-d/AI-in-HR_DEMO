from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header

from api.schemas import ChatRequest, ChatResponse
from services.runtime import chat_service


router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest, x_user: Optional[str] = Header(None)) -> ChatResponse:
    created_by = (x_user or "").strip() or "anonymous"
    return chat_service.handle_chat(req, created_by=created_by)

