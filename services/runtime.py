from __future__ import annotations

from core import settings
from workflow import WorkflowService

from .chat_service import ChatService
from .document_service import DocumentService
from .llm_service import LLMService
from .log_service import ChatLogService


workflow_service = WorkflowService(str(settings.WORKFLOW_DB))
llm_service = LLMService(
    primary_model=settings.OPENAI_MODEL,
    fallback_model=settings.OPENAI_FALLBACK_MODEL,
)
log_service = ChatLogService(
    settings.LOG_PATH,
    user_text_mode=settings.LOG_USER_TEXT_MODE,
)
document_service = DocumentService(settings.DOCUMENTS_DIR)
chat_service = ChatService(
    workflow_service=workflow_service,
    llm_service=llm_service,
    log_service=log_service,
    document_service=document_service,
)
