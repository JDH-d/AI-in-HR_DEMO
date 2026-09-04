from __future__ import annotations

from dataclasses import dataclass

from core import settings
from rag.index import KnowledgeIndex
from workflow import WorkflowService

from .ai_settings_service import AISettingsService
from .auth_service import DemoAuthService
from .chat_service import ChatService
from .conversation_service import ConversationService
from .document_service import DocumentService
from .llm_service import LLMService
from .log_service import ChatLogService


@dataclass(frozen=True)
class ServiceContainer:
    workflow: WorkflowService
    conversations: ConversationService
    ai_settings: AISettingsService
    auth: DemoAuthService
    logs: ChatLogService
    documents: DocumentService
    knowledge_index: KnowledgeIndex
    chat: ChatService


def create_services() -> ServiceContainer:
    """Build the application services without doing work at module import time."""

    conversations = ConversationService(
        settings.CONVERSATION_DB,
        legacy_db_path=settings.WORKFLOW_DB,
    )
    workflow = WorkflowService(str(settings.WORKFLOW_DB))
    ai_settings = AISettingsService(
        settings.AI_SETTINGS_PATH,
        legacy_system_prompt_path=settings.LEGACY_SYSTEM_PROMPT_PATH,
    )
    auth = DemoAuthService(
        secret=settings.DEMO_AUTH_SECRET,
        password=settings.DEMO_LOGIN_PASSWORD,
        ttl_seconds=settings.DEMO_TOKEN_TTL_SECONDS,
    )
    llm = LLMService(model=settings.OPENAI_MODEL)
    logs = ChatLogService(
        settings.LOG_PATH,
        user_text_mode=settings.LOG_USER_TEXT_MODE,
    )
    documents = DocumentService(
        settings.DOCUMENTS_DIR,
        index_path=settings.INDEX_PATH,
        index_status_path=settings.INDEX_STATUS_PATH,
    )
    knowledge_index = KnowledgeIndex(
        settings.DOCUMENTS_DIR,
        settings.INDEX_PATH,
        settings.EMBEDDING_MODEL,
    )
    chat = ChatService(
        workflow_service=workflow,
        llm_service=llm,
        log_service=logs,
        ai_settings_service=ai_settings,
        knowledge_index=knowledge_index,
    )
    return ServiceContainer(
        workflow=workflow,
        conversations=conversations,
        ai_settings=ai_settings,
        auth=auth,
        logs=logs,
        documents=documents,
        knowledge_index=knowledge_index,
        chat=chat,
    )
