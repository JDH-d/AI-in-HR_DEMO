from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app import app
from core import settings
from domain.chat import ChatQuery, ChatTurn, Intent, RoutingDecision
from domain.errors import DocumentError
from domain.workflow import WorkflowDecisionError, WorkflowNotFoundError
from integrations.embedding_service import EmbeddingError, EmbeddingService
from services.chat_fallbacks import ChatFallbackPolicy
from services.document_service import DocumentService
from services.rag_service import RAGService
from services.runtime import get_runtime
from services.workflow_service import WorkflowService
from storage.ai_settings_store import AISettingsStore
from storage.document_store import DocumentStore
from storage.prompt_store import PromptStore


@pytest.fixture
def library(tmp_path):
    store = DocumentStore(tmp_path / "documents", index_status_path=tmp_path / "status.json")
    controls = AISettingsStore(tmp_path / "controls.json")
    controls.save({"auto_index_uploads": False})
    return DocumentService(store, controls, Mock())


def test_delete_failure_restores_document_and_index_status(library):
    content = b"# Policy\nKeep this source."
    document = library.upload("Policy.md", BytesIO(content))
    library.store.record_index_result(document["id"], "indexed")
    path = library.download_path(document["id"])
    modified = path.stat().st_mtime_ns
    library.rebuild.side_effect = RuntimeError("Indexer unavailable")
    with pytest.raises(DocumentError, match="rolled back"):
        library.delete(document["id"])
    assert path.read_bytes() == content
    assert path.stat().st_mtime_ns == modified
    assert library.list_documents()[0]["index_status"] == "indexed"


def test_failed_index_can_retry_without_losing_uploaded_file(library):
    content = b"# Policy\nExisting source."
    document = library.upload("Policy.md", BytesIO(content))
    library.rebuild.side_effect = ValueError("Unreadable index")
    with pytest.raises(DocumentError):
        library.index(document["id"])
    assert library.list_documents()[0]["index_status"] == "error"
    library.rebuild.side_effect = None
    assert library.index(document["id"])["index_status"] == "indexed"
    with pytest.raises(DocumentError) as conflict:
        library.upload("Policy.md", BytesIO(b"Replacement"))
    assert conflict.value.code == "conflict"
    assert library.download_path(document["id"]).read_bytes() == content


def test_index_failure_still_has_503_api_contract(library):
    document = library.upload("Policy.md", BytesIO(b"# Policy\nContent"))
    library.rebuild.side_effect = RuntimeError("Unavailable")
    with TestClient(app) as client, patch.object(get_runtime(), "document_service", library):
        token = client.post(
            "/api/v1/auth/login",
            json={"username": "knowledge_admin", "password": settings.DEMO_LOGIN_PASSWORD},
        ).json()["access_token"]
        response = client.post(
            f"/api/v1/documents/{document['id']}/index",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 503
    assert "Index rebuild failed" in response.json()["detail"]


def test_prompt_write_failure_preserves_saved_value(tmp_path):
    store = PromptStore(tmp_path / "prompt.txt", "Default prompt")
    store.save("Сохранённый промпт")
    with patch("storage.text_store.os.replace", side_effect=OSError("Disk failure")):
        with pytest.raises(OSError):
            store.save("Replacement")
    assert store.get() == "Сохранённый промпт"
    assert list(tmp_path.glob("*.tmp")) == []


def test_live_prompt_is_loaded_and_preview_does_not_overwrite_it(tmp_path):
    prompts = PromptStore(tmp_path / "prompt.txt", "Default prompt")
    prompts.save("Saved company instruction")
    llm = Mock()
    llm.generate.return_value = "General guidance"
    retriever = Mock()
    retriever.query.return_value = []
    service = RAGService(
        llm,
        ChatFallbackPolicy(),
        index_ensurer=lambda: None,
        retriever_provider=lambda: retriever,
        prompt_store=prompts,
    )
    query = ChatQuery(messages=[ChatTurn(role="user", content="How does relocation work?")])
    decision = RoutingDecision(
        language="en",
        intent=Intent.WORK,
        topic_selection=None,
        explicit_topic_choice=False,
        prior_topic=None,
    )
    service.answer_with_retrieval(query, decision, settings={"strict_grounding": False})
    assert "Saved company instruction" in llm.generate.call_args.args[0][0]["content"][0]["text"]
    service.answer_with_retrieval(
        query, decision, settings={"strict_grounding": False}, system_prompt="Preview only"
    )
    assert "Preview only" in llm.generate.call_args.args[0][0]["content"][0]["text"]
    assert prompts.get() == "Saved company instruction"


def test_manager_rules_and_request_visibility_apply_without_http(tmp_path):
    service = WorkflowService(str(tmp_path / "workflow.db"))
    draft = service.create_structured_draft(
        request_type="document",
        start_date=None,
        end_date=None,
        comment="Letter",
        applicant="employee",
        approver="manager",
    )
    with pytest.raises(WorkflowNotFoundError):
        service.get_visible(draft["id"], "other_employee", employee=True)
    with pytest.raises(WorkflowNotFoundError):
        service.get_visible(draft["id"], "manager", employee=False)
    submitted = service.confirm_draft(draft["id"], "employee", {})
    assert service.get_visible(draft["id"], "manager", employee=False)["id"] == draft["id"]
    review = service.act(draft["id"], "manager", "manager", "start_review", submitted["revision"])
    with pytest.raises(WorkflowDecisionError):
        service.act(
            draft["id"],
            "manager",
            "manager",
            "reject",
            review["revision"],
            comment="Reason",
            basis="Policy",
            fair_review_confirmed=False,
        )
    assert (
        service.act(
            draft["id"],
            "manager",
            "manager",
            "reject",
            review["revision"],
            comment="Reason",
            basis="Policy",
            fair_review_confirmed=True,
        )["status"]
        == "rejected"
    )


def test_embedding_batches_preserve_input_order_and_check_count():
    client = Mock()
    client.embeddings.create.side_effect = [
        SimpleNamespace(
            data=[
                SimpleNamespace(index=1, embedding=[2.0]),
                SimpleNamespace(index=0, embedding=[1.0]),
            ]
        ),
        SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[3.0])]),
    ]
    service = EmbeddingService("test-model", client_factory=lambda: client, batch_size=2)
    assert service.embed(["one", "two", "three"]) == [[1.0], [2.0], [3.0]]
    client.embeddings.create.side_effect = None
    client.embeddings.create.return_value = SimpleNamespace(data=[])
    with pytest.raises(EmbeddingError):
        service.embed(["one"])


def test_hiding_sources_does_not_erase_grounding_from_quality_logs():
    from domain.chat import ChatOutcome, RetrievedChunk
    from services.chat_service import ChatService

    source = RetrievedChunk("policy.md", 0, "Policy", "Payroll", "HR", "1", "Evidence", 0.9)
    workflow, logs, rag, router = Mock(), Mock(), Mock(), Mock()
    workflow.prepare_draft.return_value = None
    router.route.return_value = RoutingDecision("en", Intent.WORK, None, False, None)
    rag.answer_with_retrieval.return_value = ChatOutcome("Answer", Intent.WORK, "en", [source])
    service = ChatService(workflow, Mock(), logs, router=router, rag_service=rag)
    outcome = service.respond(
        ChatQuery([ChatTurn("user", "When is payroll?")]),
        "employee",
        settings={"show_sources": False},
    )
    assert outcome.sources == []
    assert logs.append_chat.call_args.kwargs["sources"][0]["source"] == "policy.md"
