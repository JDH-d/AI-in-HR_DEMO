from __future__ import annotations

from pathlib import Path

from rag.index import KnowledgeIndex
from services.ai_settings_service import AISettingsService
from services.auth_service import DemoAuthService
from services.chat_service import ChatService
from services.conversation_service import ConversationService
from services.document_service import DocumentService
from services.llm_service import LLMService
from services.log_service import ChatLogService
from services.runtime import ServiceContainer
from workflow import WorkflowService

TEST_PASSWORD = "demo-password"


def build_test_services(root: Path) -> ServiceContainer:
    root.mkdir(parents=True, exist_ok=True)
    documents_dir = root / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    database_path = root / "peopleflow.db"
    workflow = WorkflowService(str(database_path))
    conversations = ConversationService(root / "conversations.db")
    ai_settings = AISettingsService(root / "ai_settings.json")
    auth = DemoAuthService("test-only-auth-secret", TEST_PASSWORD)
    llm = LLMService("test-model", client_factory=_unavailable_client)
    logs = ChatLogService(root / "chat.jsonl", user_text_mode="masked")
    documents = DocumentService(
        documents_dir,
        index_path=root / "index.json",
        index_status_path=root / "index_status.json",
    )
    knowledge_index = KnowledgeIndex(
        documents_dir,
        root / "index.json",
        "test-embedding-model",
        client_factory=_unavailable_client,
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


def _unavailable_client():
    raise ValueError("External services are disabled in tests")
