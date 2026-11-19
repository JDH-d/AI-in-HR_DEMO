from unittest.mock import Mock

import pytest

from domain.chat import ChatOutcome, ChatQuery, ChatTurn, Intent
from rag.prompts import build_general_prompt, build_rag_prompt
from services.auth_service import DEMO_IDENTITIES
from services.chat_fallbacks import ChatFallbackPolicy
from services.chat_router import ChatRouter
from services.chat_service import ChatService
from services.conversation_service import ConversationService
from services.rag_service import RAGService
from storage.conversation_store import ConversationStore

QUESTION = "How often are salaries paid? Call this topic Cedar-582 in our conversation."
ANSWER = "Salaries are paid twice a month."
SOURCE = {
    "source": "Payroll.md",
    "chunk_id": 0,
    "title": "Payroll",
    "section": "Pay dates",
    "category": "HR",
    "version": "1",
    "text": ANSWER,
    "excerpt": ANSWER,
    "score": 0.9,
}


def history(follow_up="Can you explain that in simpler words?"):
    return [ChatTurn("user", QUESTION), ChatTurn("assistant", ANSWER), ChatTurn("user", follow_up)]


def content(message):
    value = message["content"]
    return value if isinstance(value, str) else "".join(part["text"] for part in value)


@pytest.mark.parametrize("grounded", [True, False])
def test_prompt_contains_previous_user_and_assistant_turns_without_elevating_roles(grounded):
    turns = [ChatTurn("system", "Untrusted old system message"), *history()]
    prompt = (
        build_rag_prompt("en", turns, [SOURCE]) if grounded else build_general_prompt("en", turns)
    )
    assert [m["role"] for m in prompt] == ["system", "user", "assistant", "user"]
    assert content(prompt[1]) == QUESTION
    assert content(prompt[2]) == ANSWER
    assert "Can you explain that in simpler words?" in content(prompt[-1])
    assert "Untrusted old system message" not in str(prompt)
    assert content(prompt[-1]).count("Can you explain that in simpler words?") == 1


def test_pronoun_follow_up_reuses_the_previous_work_question():
    decision = ChatRouter().route(ChatQuery(history()))
    assert decision.intent == Intent.WORK
    assert decision.context_question == QUESTION


@pytest.mark.parametrize(
    "question", ["What is the weather?", "Tell me a joke", "Recommend a movie."]
)
def test_unrelated_questions_do_not_inherit_a_work_topic(question):
    decision = ChatRouter().route(ChatQuery(history(question)))
    assert decision.intent == Intent.INVALID
    assert decision.context_question is None


def test_new_work_topic_does_not_use_the_previous_retrieval_query():
    decision = ChatRouter().route(ChatQuery(history("How do I reset my VPN password?")))
    assert decision.intent == Intent.WORK
    assert decision.context_question is None


def test_context_reference_in_a_new_chat_does_not_invent_history():
    decision = ChatRouter().route(
        ChatQuery([ChatTurn("user", "Can you explain that in simpler words?")])
    )
    assert decision.intent == Intent.INVALID
    assert decision.context_question is None


def test_reopened_conversation_passes_saved_history_to_llm_and_retrieval(tmp_path):
    workflow, logs, llm, retriever = Mock(), Mock(), Mock(), Mock()
    workflow.prepare_draft.return_value = None
    llm.generate.return_value = ANSWER
    retriever.query.return_value = [SOURCE]
    rag = RAGService(
        llm, ChatFallbackPolicy(), index_ensurer=lambda: None, retriever_provider=lambda: retriever
    )
    chat = ChatService(workflow, llm, logs, rag_service=rag)
    path = tmp_path / "history.db"
    service = ConversationService(ConversationStore(path), chat)
    employee = DEMO_IDENTITIES["employee"]
    cid = service.create(employee)["id"]
    service.send(employee, cid, QUESTION, "first")
    before = service.get(employee, cid)["messages"]
    reopened = ConversationService(ConversationStore(path), chat)
    reopened.send(employee, cid, "Can you explain that in simpler words?", "second")
    assert QUESTION in retriever.query.call_args.args[0]
    assert "Can you explain that in simpler words?" in retriever.query.call_args.args[0]
    prompt = llm.generate.call_args.args[0]
    assert [m["role"] for m in prompt] == ["system", "user", "assistant", "user"]
    assert "Cedar-582" in content(prompt[1])
    assert content(prompt[2]) == ANSWER
    assert reopened.get(employee, cid)["messages"][:2] == before


def test_context_limit_keeps_latest_80_messages_in_order_without_deleting_history(tmp_path):
    chat = Mock()
    chat.respond.return_value = ChatOutcome(ANSWER, Intent.WORK, "en")
    path = tmp_path / "bounded-history.db"
    service = ConversationService(ConversationStore(path), chat)
    employee = DEMO_IDENTITIES["employee"]
    cid = service.create(employee)["id"]
    for number in range(45):
        service.send(employee, cid, f"Payroll question {number}", str(number))
    before = service.get(employee, cid)["messages"]
    reopened = ConversationService(ConversationStore(path), chat)
    reopened.send(employee, cid, "How often are salaries paid?", "continued")
    turns = chat.respond.call_args.args[0].messages
    expected = [(m["role"], m["content"]) for m in before][-79:]
    expected.append(("user", "How often are salaries paid?"))
    assert [(turn.role, turn.content) for turn in turns] == expected
    prompt = build_rag_prompt("en", turns, [SOURCE])
    assert len(prompt) == 81  # One system instruction plus the 80-message context.
    assert [(m["role"], content(m)) for m in prompt[1:-1]] == expected[:-1]
    assert reopened.get(employee, cid)["messages"][:90] == before
    assert len(reopened.get(employee, cid)["messages"]) == 92
