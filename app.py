from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.conversation_routes import router as conversation_router
from api.error_handlers import register_error_handlers
from api.http_security import HTTPGuardMiddleware
from api.integration_routes import router as integration_router
from api.personal_integration_routes import router as personal_integration_router
from api.v1_routes import router as v1_router
from core.settings import CORS_ORIGINS
from services.runtime import get_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    notifications = get_runtime().notification_service
    if notifications:
        notifications.start()
    try:
        yield
    finally:
        if notifications:
            await notifications.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="AI HR Knowledge Assistant API", version="2.2.0", lifespan=lifespan)
    app.add_middleware(HTTPGuardMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    register_error_handlers(app)

    app.include_router(v1_router)
    app.include_router(conversation_router)
    app.include_router(integration_router)
    app.include_router(personal_integration_router)
    return app


app = create_app()
