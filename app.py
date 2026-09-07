from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.v1_routes import router as v1_router
from core.settings import CORS_ORIGINS
from services.runtime import ServiceContainer, create_services


def create_app(
    service_factory: Callable[[], ServiceContainer] = create_services,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.services = service_factory()
        yield

    application = FastAPI(
        title="AI HR Knowledge Assistant API",
        version="3.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.include_router(v1_router)
    return application


app = create_app()
