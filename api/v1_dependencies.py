from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.auth_service import AuthenticationError, DemoIdentity
from services.runtime import ServiceContainer

bearer_scheme = HTTPBearer(auto_error=False)


def get_services(request: Request) -> ServiceContainer:
    services = getattr(request.app.state, "services", None)
    if not isinstance(services, ServiceContainer):
        raise RuntimeError("Application services are not initialized")
    return services


Services = Annotated[ServiceContainer, Depends(get_services)]


def current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    services: ServiceContainer = Depends(get_services),
) -> DemoIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer authentication is required.")
    try:
        return services.auth.verify_token(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def require_roles(*roles: str) -> Callable:
    def dependency(identity: DemoIdentity = Depends(current_identity)) -> DemoIdentity:
        if identity.role not in roles:
            raise HTTPException(status_code=403, detail="This role cannot perform this action.")
        return identity

    return dependency
