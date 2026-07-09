from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException

from core.settings import ADMIN_TOKEN


def require_admin(
    x_admin_token: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> None:
    if not ADMIN_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="Administrator access is not configured for this environment.",
        )
    provided = _extract_token(x_admin_token, authorization)
    if not provided or provided != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Administrator authentication failed.")


def _extract_token(
    x_admin_token: Optional[str], authorization: Optional[str]
) -> Optional[str]:
    if x_admin_token:
        return x_admin_token.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None
