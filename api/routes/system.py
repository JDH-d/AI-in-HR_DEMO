from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.v1_dependencies import Services, current_identity
from api.v1_schemas import LoginRequest
from core.settings import configuration_warnings
from services.auth_service import AuthenticationError, DemoIdentity

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health")
def health(services: Services) -> dict:
    return {
        "status": "ok",
        "api_version": "v1",
        "knowledge_index": services.documents.index_health(),
        "configuration_warnings": configuration_warnings(),
    }


@router.post("/auth/login")
def login(payload: LoginRequest, services: Services) -> dict:
    try:
        token, identity = services.auth.login(payload.username, payload.password)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": services.auth.ttl_seconds,
        "user": identity.public_dict(),
    }


@router.get("/me")
def me(identity: DemoIdentity = Depends(current_identity)) -> dict:
    return {"user": identity.public_dict()}
