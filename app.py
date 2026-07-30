from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.v1_routes import router as v1_router
from core.settings import CORS_ORIGINS
from services.runtime import slack_action_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    slack_action_service.start()
    try:
        yield
    finally:
        slack_action_service.stop()


app = FastAPI(
    title="AI HR Knowledge Assistant API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(v1_router)
