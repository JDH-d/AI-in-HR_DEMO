from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from core import settings
from integrations.llm_service import LLMService
from rag.index import rebuild_index
from rag.prompts import DEFAULT_SYSTEM_PROMPT
from services.ai_settings_service import AISettingsService
from services.auth_service import DEMO_IDENTITIES, DemoAuthService
from services.chat_service import ChatService
from services.conversation_service import ConversationService
from services.document_service import DocumentService
from services.notification_service import NotificationService
from services.quality_service import QualityService
from services.workflow_service import WorkflowService
from storage.ai_settings_store import AISettingsStore
from storage.chat_log_store import ChatLogStore
from storage.conversation_store import ConversationStore
from storage.document_store import DocumentStore
from storage.prompt_store import PromptStore


@dataclass
class Runtime:
    workflow_service: WorkflowService
    auth_service: DemoAuthService
    chat_service: ChatService
    document_service: DocumentService
    ai_settings_service: AISettingsService
    quality_service: QualityService
    conversation_service: ConversationService
    notification_service: NotificationService | None = None


@lru_cache(maxsize=1)
def get_runtime() -> Runtime:
    """Compose services on startup, without creating files when modules are imported."""
    settings.validate_auth_settings()
    auth = DemoAuthService(
        settings.DEMO_AUTH_SECRET, settings.DEMO_LOGIN_PASSWORD, settings.DEMO_TOKEN_TTL_SECONDS
    )
    workflow = WorkflowService(str(settings.WORKFLOW_DB))
    ai_settings = AISettingsStore(settings.AI_SETTINGS_PATH)
    llm = LLMService(settings.OPENAI_MODEL)
    logs = ChatLogStore(settings.LOG_PATH, user_text_mode=settings.LOG_USER_TEXT_MODE)
    documents = DocumentStore(
        settings.DOCUMENTS_DIR,
        index_path=settings.INDEX_PATH,
        index_status_path=settings.INDEX_STATUS_PATH,
    )
    prompts = PromptStore(settings.SYSTEM_PROMPT_PATH, DEFAULT_SYSTEM_PROMPT)
    chat = ChatService(workflow, llm, logs, ai_settings_store=ai_settings, prompt_store=prompts)
    conversations = ConversationService(
        ConversationStore(settings.WORKFLOW_DB),
        chat,
        # One embedding request, semantic section selection, then answer generation.
        lease_seconds=3 * settings.OPENAI_TIMEOUT_SECONDS * (settings.OPENAI_MAX_RETRIES + 1) + 90,
    )
    for identity in DEMO_IDENTITIES.values():
        conversations.record_user(identity)
    return Runtime(
        workflow_service=workflow,
        auth_service=auth,
        chat_service=chat,
        document_service=DocumentService(documents, ai_settings, rebuild_index),
        ai_settings_service=AISettingsService(ai_settings, prompts),
        quality_service=QualityService(workflow, logs, documents),
        conversation_service=conversations,
        notification_service=NotificationService(
            settings.WORKFLOW_DB,
            slack_token=settings.SLACK_BOT_TOKEN,
            slack_signing_secret=settings.SLACK_SIGNING_SECRET,
            slack_team_id=settings.SLACK_TEAM_ID,
            discord_token=settings.DISCORD_BOT_TOKEN,
            discord_public_key=settings.DISCORD_PUBLIC_KEY,
            discord_application_id=settings.DISCORD_APPLICATION_ID,
            discord_connection_mode=settings.DISCORD_CONNECTION_MODE,
            app_url=settings.APP_PUBLIC_URL,
        ),
    )
