from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header

from services.runtime import workflow_service


router = APIRouter()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/requests")
def list_requests(x_user: Optional[str] = Header(None)) -> dict:
    created_by = (x_user or "").strip() or "anonymous"
    return {"requests": workflow_service.list_for_user(created_by)}

