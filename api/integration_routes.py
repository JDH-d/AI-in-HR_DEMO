"""Administrator-only controls. Secrets are configured exclusively on the server."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from api.v1_dependencies import require_roles
from domain.notifications import (
    IntegrationConflict,
    IntegrationError,
    IntegrationRateLimited,
    IntegrationUnavailable,
)
from services.auth_service import DemoIdentity
from services.runtime import Runtime, get_runtime


class IntegrationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            try:
                return await original(request)
            except RequestValidationError:
                # Do not echo an accidentally submitted credential in validation errors.
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": "Invalid integration settings. Credentials must be configured on the server."
                    },
                )
            except IntegrationConflict as exc:
                raise HTTPException(409, str(exc)) from None
            except IntegrationUnavailable as exc:
                raise HTTPException(503, str(exc)) from None
            except IntegrationRateLimited as exc:
                raise HTTPException(429, str(exc), headers={"Retry-After": "30"}) from None
            except IntegrationError as exc:
                raise HTTPException(400, str(exc)) from None

        return handle


def no_store(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/api/v1/admin/integrations",
    route_class=IntegrationRoute,
    dependencies=[Depends(no_store)],
)
Provider = Literal["slack", "discord"]
administrator = require_roles("knowledge_admin")


class IntegrationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    expected_revision: int = Field(..., ge=0)


class IntegrationTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    audience: Literal["employee", "manager"] = "manager"


@router.get("")
def get_integrations(
    _: DemoIdentity = Depends(administrator), runtime: Runtime = Depends(get_runtime)
):
    return runtime.notification_service.overview()


@router.patch("/{provider}")
def update_integration(
    provider: Provider,
    payload: IntegrationUpdate,
    identity: DemoIdentity = Depends(administrator),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.notification_service.set_enabled(
        provider, payload.enabled, payload.expected_revision, identity.id
    )


@router.post("/{provider}/test", status_code=202)
def test_integration(
    provider: Provider,
    payload: IntegrationTest,
    _: DemoIdentity = Depends(administrator),
    runtime: Runtime = Depends(get_runtime),
):
    return runtime.notification_service.test_notification(provider, payload.audience)
