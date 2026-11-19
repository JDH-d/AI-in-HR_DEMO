from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from services.auth_service import DemoIdentity
from services.runtime import Runtime, get_runtime

bearer_scheme = HTTPBearer(auto_error=False)


def current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    runtime: Runtime = Depends(get_runtime),
) -> DemoIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer authentication is required.")
    return runtime.auth_service.verify_token(credentials.credentials)


def require_roles(*roles: str) -> Callable:
    def dependency(identity: DemoIdentity = Depends(current_identity)) -> DemoIdentity:
        if identity.role not in roles:
            raise HTTPException(status_code=403, detail="This role cannot perform this action.")
        return identity

    return dependency
