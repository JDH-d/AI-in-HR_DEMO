from fastapi import APIRouter

from api.routes.admin import router as admin_router
from api.routes.chat import router as chat_router
from api.routes.documents import router as documents_router
from api.routes.requests import router as requests_router
from api.routes.system import router as system_router

router = APIRouter()
router.include_router(system_router)
router.include_router(chat_router)
router.include_router(requests_router)
router.include_router(documents_router)
router.include_router(admin_router)
