from __future__ import annotations

from fastapi import FastAPI

from api.admin_routes import router as admin_router
from api.chat_routes import router as chat_router
from api.public_routes import router as public_router

app = FastAPI(title="AI HR Knowledge Assistant", version="1.0.0")
app.include_router(public_router)
app.include_router(chat_router)
app.include_router(admin_router)
