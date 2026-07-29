from __future__ import annotations

from core import settings
from workflow import WorkflowService

from .ai_settings_service import AISettingsService
from .auth_service import DemoAuthService
from .chat_service import ChatService
from .conversation_service import ConversationService
from .document_service import DocumentService
from .llm_service import LLMService
from .log_service import ChatLogService
from .slack_notification_service import SlackNotificationService

workflow_service = WorkflowService(str(settings.WORKFLOW_DB))
conversation_service = ConversationService(str(settings.WORKFLOW_DB))
ai_settings_service = AISettingsService(settings.AI_SETTINGS_PATH)
auth_service = DemoAuthService(
    secret=settings.DEMO_AUTH_SECRET,
    password=settings.DEMO_LOGIN_PASSWORD,
    ttl_seconds=settings.DEMO_TOKEN_TTL_SECONDS,
)
llm_service = LLMService(
    model=settings.OPENAI_MODEL,
)
log_service = ChatLogService(
    settings.LOG_PATH,
    user_text_mode=settings.LOG_USER_TEXT_MODE,
)
slack_notification_service = SlackNotificationService(
    enabled=settings.SLACK_NOTIFICATIONS_ENABLED,
    webhook_url=settings.SLACK_WEBHOOK_URL,
    public_web_base_url=settings.PUBLIC_WEB_BASE_URL,
    timeout_seconds=settings.SLACK_TIMEOUT_SECONDS,
)
document_service = DocumentService(
    settings.DOCUMENTS_DIR,
    index_path=settings.INDEX_PATH,
    index_status_path=settings.INDEX_STATUS_PATH,
)
chat_service = ChatService(
    workflow_service=workflow_service,
    llm_service=llm_service,
    log_service=log_service,
    document_service=document_service,
    ai_settings_service=ai_settings_service,
)
