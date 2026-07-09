from __future__ import annotations

import base64
import html
import math
import os
import time

import requests
import streamlit as st

from rag.nlp import SUPPORTED_TOPICS

from web_ui.api_client import (
    DemoAPIClient,
    extract_assistant_content,
    extract_assistant_sources,
    format_http_error,
    safe_json,
)
from web_ui.composer import ComposerAction, render_composer, render_composer_styles
from web_ui.demo_prompts import (
    DEMO_PROMPTS,
    DemoPromptsAction,
    iter_demo_prompts,
    render_demo_prompt_styles,
    render_demo_prompts,
)


MAX_CONTEXT_MESSAGES = 12
REQUEST_TIMEOUT_SEC = 30

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
USER_AVATAR = os.path.join(ASSETS_DIR, "user.png")
BOT_AVATAR = os.path.join(ASSETS_DIR, "bot.png")


def _img_to_data_uri(path: str) -> str:
    with open(path, "rb") as handle:
        data = base64.b64encode(handle.read()).decode("utf-8")
    return f"data:image/png;base64,{data}"


def _build_messages_payload(history: list[dict], prompt: str) -> list[dict]:
    payload: list[dict] = []
    for item in history:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant", "system"}:
            continue
        if not content:
            continue
        payload.append({"role": role, "content": content})
    payload.append({"role": "user", "content": prompt.strip()})
    return payload[-MAX_CONTEXT_MESSAGES:]


def _truncate_source_text(text: str, max_chars: int = 150) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _build_sources_markup(sources: list[dict] | None) -> str:
    if not sources:
        return ""

    cards: list[str] = []
    for source in sources[:3]:
        source_name = html.escape(str(source.get("source", "")))
        chunk_id = source.get("chunk_id", "-")
        excerpt = html.escape(_truncate_source_text(str(source.get("text", ""))))
        cards.append(
            (
                '<div class="source-card">'
                '<div class="source-card-meta">'
                f'<span class="source-name">{source_name}#{chunk_id}</span>'
                "</div>"
                f'<div class="source-text">{excerpt}</div>'
                "</div>"
            )
        )

    return (
        '<div class="source-block">'
        '<div class="source-block-title">Sources used</div>'
        f'{"".join(cards)}'
        "</div>"
    )


def _build_typing_message_markup(avatar_data: str) -> str:
    return (
        '<div class="chat-row assistant-row">'
        f'<img class="chat-avatar assistant-avatar" src="{avatar_data}" alt="assistant" />'
        '<div class="chat-stack assistant-stack">'
        '<div class="assistant-bubble typing-bubble">'
        '<span class="typing-dots" aria-label="Assistant is typing">'
        "<span></span><span></span><span></span>"
        "</span>"
        "</div>"
        "</div>"
        "</div>"
    )


def _iter_typing_frames(text: str, max_steps: int = 28) -> list[str]:
    if not text:
        return [""]
    step_size = max(1, math.ceil(len(text) / max_steps))
    frames = [text[:idx] for idx in range(step_size, len(text), step_size)]
    frames.append(text)
    return frames


def _build_chat_message_markup(
    role: str,
    content: str,
    avatar_data: str,
    sources: list[dict] | None = None,
    show_cursor: bool = False,
) -> str:
    safe_content = html.escape(content or "").replace("\n", "<br>")
    if show_cursor:
        safe_content += '<span class="typing-caret" aria-hidden="true"></span>'
    if role == "assistant":
        row_class = "assistant-row"
        stack_class = "assistant-stack"
        bubble_class = "assistant-bubble"
        avatar_class = "assistant-avatar"
        alt = "assistant"
        sources_markup = _build_sources_markup(sources)
    else:
        row_class = "user-row"
        stack_class = "user-stack"
        bubble_class = "user-bubble"
        avatar_class = "user-avatar"
        alt = "user"
        sources_markup = ""

    avatar_markup = f'<img class="chat-avatar {avatar_class}" src="{avatar_data}" alt="{alt}" />'
    stack_markup = (
        f'<div class="chat-stack {stack_class}">'
        f'<div class="{bubble_class}">{safe_content}</div>'
        f"{sources_markup}"
        "</div>"
    )

    if role == "assistant":
        body_markup = avatar_markup + stack_markup
    else:
        body_markup = stack_markup + avatar_markup

    return f'<div class="chat-row {row_class}">{body_markup}</div>'


def _render_empty_state() -> None:
    st.markdown(
        """
        <div class="demo-hero">
            <div class="hero-kicker">Employee Self-Service Demo</div>
            <h3>Grounded company knowledge with workflow follow-through.</h3>
            <p>
                This assistant is designed for document-backed employee support, not generic small talk.
                Ask a question, create a request, and then review the result in the admin console.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    topic_items = "".join(f"<li>{html.escape(topic)}</li>" for topic in SUPPORTED_TOPICS)
    st.markdown(
        f"""
        <div class="topic-panel">
            <div class="topic-panel-title">Supported Topics</div>
            <ul>{topic_items}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="composer-tip">
            Use the <strong>+</strong> button in the message bar to open {len(iter_demo_prompts(DEMO_PROMPTS))} demo prompts,
            including valid company-policy questions, neutral greetings, and a couple of unsupported test prompts.
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_chat_message(
    role: str,
    content: str,
    avatar_data: str,
    sources: list[dict] | None = None,
) -> None:
    st.markdown(
        _build_chat_message_markup(role, content, avatar_data, sources=sources),
        unsafe_allow_html=True,
    )


def _stream_assistant_response(
    placeholder,
    content: str,
    avatar_data: str,
    sources: list[dict] | None = None,
) -> None:
    placeholder.markdown(
        _build_typing_message_markup(avatar_data),
        unsafe_allow_html=True,
    )

    frames = _iter_typing_frames(content)
    total_duration = min(1.2, max(0.45, len(content) * 0.012))
    initial_pause = min(0.3, total_duration * 0.3)
    frame_pause = max(0.02, (total_duration - initial_pause) / max(len(frames), 1))

    time.sleep(initial_pause)
    for frame in frames[:-1]:
        placeholder.markdown(
            _build_chat_message_markup(
                "assistant",
                frame,
                avatar_data,
                show_cursor=True,
            ),
            unsafe_allow_html=True,
        )
        time.sleep(frame_pause)

    placeholder.markdown(
        _build_chat_message_markup(
            "assistant",
            content,
            avatar_data,
            sources=sources,
        ),
        unsafe_allow_html=True,
    )


def _initialize_state() -> None:
    defaults = {
        "messages": [],
        "user_id": "",
        "composer_draft": "",
        "drawer_open": False,
        "request_in_flight": False,
        "queued_prompt": "",
        "show_requests": False,
        "user_requests": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _handle_composer_action(action: ComposerAction) -> None:
    if action.kind == "toggle_drawer":
        st.session_state.drawer_open = not st.session_state.drawer_open
        st.rerun()


def _handle_demo_prompts_action(action: DemoPromptsAction) -> None:
    if action.kind == "close":
        st.session_state.drawer_open = False
        st.rerun()

    if action.kind == "submit_demo":
        st.session_state.queued_prompt = action.prompt
        st.session_state.drawer_open = False
        st.session_state.request_in_flight = True
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="AI HR Knowledge Assistant", layout="centered")
    st.title("AI HR Knowledge Assistant")
    st.caption("Demo environment for internal knowledge, policy guidance, and workflow requests.")

    st.markdown(
        """
        <style>
        .chat-row {
            display: flex;
            width: 100%;
            gap: 12px;
            margin: 14px 0;
            align-items: flex-end;
        }

        .assistant-row {
            justify-content: flex-start;
        }

        .user-row {
            justify-content: flex-end;
        }

        .chat-stack {
            display: flex;
            flex-direction: column;
            gap: 8px;
            max-width: min(78%, 700px);
        }

        .assistant-stack {
            align-items: flex-start;
        }

        .user-stack {
            align-items: flex-end;
        }

        .chat-avatar {
            width: 38px;
            height: 38px;
            border: 1px solid #344154;
            border-radius: 12px;
            padding: 6px;
            box-sizing: border-box;
            flex: 0 0 auto;
        }

        .assistant-avatar {
            background: linear-gradient(145deg, #18212d, #0f1723);
            box-shadow: 0 8px 18px rgba(8, 15, 28, 0.28);
        }

        .user-avatar {
            background: linear-gradient(145deg, #0f2d66, #173f8f);
            box-shadow: 0 10px 18px rgba(20, 53, 121, 0.26);
        }

        .assistant-bubble,
        .user-bubble {
            padding: 14px 16px;
            line-height: 1.55;
            box-shadow: 0 12px 28px rgba(15, 23, 36, 0.16);
            word-break: break-word;
        }

        .assistant-bubble {
            color: #e6edf7;
            background: linear-gradient(180deg, #1c2431, #161e29);
            border: 1px solid #313c4d;
            border-radius: 18px 18px 18px 8px;
        }

        .user-bubble {
            color: #f8fbff;
            background: linear-gradient(135deg, #1d4ed8, #2563eb 58%, #3b82f6);
            border: 1px solid #6ea8ff;
            border-radius: 18px 18px 8px 18px;
        }

        .typing-bubble {
            min-width: 74px;
            min-height: 54px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
        }

        .demo-hero {
            background: linear-gradient(135deg, rgba(32,39,52,0.96), rgba(19,29,41,0.96));
            border: 1px solid #2d3748;
            border-radius: 18px;
            padding: 18px 20px;
            margin: 8px 0 16px 0;
        }

        .demo-hero h3 {
            margin: 4px 0 8px 0;
            font-size: 1.15rem;
        }

        .demo-hero p {
            margin: 0;
            color: #b9c2cf;
            line-height: 1.5;
        }

        .hero-kicker {
            font-size: 0.76rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #8ab4ff;
        }

        .topic-panel {
            border: 1px solid #273244;
            background: rgba(20, 27, 37, 0.82);
            border-radius: 16px;
            padding: 14px 16px;
            margin-bottom: 14px;
        }

        .topic-panel-title {
            font-weight: 600;
            margin-bottom: 8px;
        }

        .topic-panel ul {
            margin: 0;
            padding-left: 18px;
            color: #ced6e1;
        }

        .topic-panel li {
            margin: 4px 0;
        }

        .composer-tip {
            color: #aab6c9;
            font-size: 0.93rem;
            line-height: 1.45;
            margin: 0 0 18px 0;
        }

        .source-block {
            width: 100%;
        }

        .source-block-title {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #92a3bd;
            margin: 0 0 6px 4px;
        }

        .source-card {
            background: rgba(18, 25, 35, 0.92);
            border: 1px solid #2c3747;
            border-radius: 12px;
            padding: 10px 12px;
            margin-top: 6px;
        }

        .source-card-meta {
            display: flex;
            justify-content: space-between;
            gap: 10px;
            margin-bottom: 4px;
            font-size: 0.85rem;
        }

        .source-name {
            color: #e5ebf3;
            font-weight: 600;
        }

        .source-text {
            color: #b7c0cd;
            font-size: 0.9rem;
            line-height: 1.4;
        }

        .typing-dots span {
            display: inline-block;
            width: 6px;
            height: 6px;
            background: #8a93a3;
            border-radius: 50%;
            opacity: 0.6;
            animation: typing-bounce 1s infinite ease-in-out;
        }

        .typing-dots span:nth-child(2) {
            animation-delay: 0.2s;
        }

        .typing-dots span:nth-child(3) {
            animation-delay: 0.4s;
        }

        .typing-caret {
            display: inline-block;
            width: 0.55ch;
            height: 1.1em;
            margin-left: 2px;
            vertical-align: text-bottom;
            border-radius: 2px;
            background: currentColor;
            animation: caret-blink 0.9s steps(1) infinite;
            opacity: 0.85;
        }

        @keyframes typing-bounce {
            0%, 80%, 100% {
                transform: translateY(0);
                opacity: 0.5;
            }
            40% {
                transform: translateY(-4px);
                opacity: 1;
            }
        }

        @keyframes caret-blink {
            0%, 45% {
                opacity: 0.85;
            }
            46%, 100% {
                opacity: 0;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    render_composer_styles()
    render_demo_prompt_styles()

    api_client = DemoAPIClient(timeout_seconds=REQUEST_TIMEOUT_SEC)
    _initialize_state()
    if st.session_state.request_in_flight and st.session_state.composer_draft:
        st.session_state.composer_draft = ""

    query_user_id = ""
    if hasattr(st, "query_params"):
        query_user_id = str(st.query_params.get("user_id", "")).strip()
    elif hasattr(st, "experimental_get_query_params"):
        query_user_id = str((st.experimental_get_query_params().get("user_id") or [""])[0]).strip()
    if query_user_id and not st.session_state.user_id:
        st.session_state.user_id = query_user_id
    active_user_id = str(st.session_state.get("user_id", "")).strip() or None

    def _fetch_requests() -> None:
        try:
            resp = api_client.list_requests(active_user_id)
            data = safe_json(resp)
            if resp.status_code == 200:
                if isinstance(data, dict):
                    st.session_state.user_requests = data.get("requests", [])
                else:
                    st.session_state.user_requests = []
            else:
                st.session_state.user_requests = []
                st.error(format_http_error(resp, data))
        except requests.RequestException as exc:
            st.session_state.user_requests = []
            st.error(f"The API is currently unavailable: {exc}")

    with st.sidebar:
        st.subheader("Session")
        st.text_input(
            "User ID",
            key="user_id",
            help="Applied automatically to chat requests and request history in this demo session.",
        )
        if st.button("View My Requests", help="Open my workflow requests"):
            st.session_state.show_requests = True
        if st.button("Clear Conversation", help="Clear the current conversation"):
            st.session_state.messages = []
            st.session_state.composer_draft = ""
            st.session_state.drawer_open = False
            st.session_state.request_in_flight = False
            st.session_state.queued_prompt = ""
            st.rerun()

    if st.session_state.get("show_requests"):
        if hasattr(st, "dialog"):

            @st.dialog("My Requests")
            def _requests_dialog():
                _fetch_requests()
                data = st.session_state.get("user_requests", [])
                if data:
                    st.dataframe(data, width="stretch", height=520)
                else:
                    st.caption("No workflow requests are available for this user.")
                if st.button("Close Panel"):
                    st.session_state.show_requests = False
                    st.rerun()

            _requests_dialog()
        else:
            st.warning("This Streamlit version does not support modal dialogs.")
            st.session_state.show_requests = False

    user_avatar_data = _img_to_data_uri(USER_AVATAR)
    bot_avatar_data = _img_to_data_uri(BOT_AVATAR)
    queued_prompt = str(st.session_state.get("queued_prompt", "")).strip()
    request_in_flight = bool(st.session_state.get("request_in_flight", False))
    empty_state_area = st.container()
    chat_area = st.container()
    composer_area = st.container()
    drawer_area = st.container()

    with empty_state_area:
        if not st.session_state.messages and not queued_prompt:
            _render_empty_state()

    for msg in st.session_state.messages:
        with chat_area:
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            avatar_data = bot_avatar_data if role == "assistant" else user_avatar_data
            sources = msg.get("sources") if role == "assistant" else None
            _render_chat_message(role, content, avatar_data, sources=sources)

    response_placeholder = None
    with chat_area:
        if request_in_flight and queued_prompt:
            _render_chat_message("user", queued_prompt, user_avatar_data)
            response_placeholder = st.empty()
            response_placeholder.markdown(
                _build_typing_message_markup(bot_avatar_data),
                unsafe_allow_html=True,
            )

    with composer_area:
        composer_action = render_composer(disabled=request_in_flight)
    with drawer_area:
        if not request_in_flight and st.session_state.drawer_open:
            demo_action = render_demo_prompts(DEMO_PROMPTS)
            _handle_demo_prompts_action(demo_action)

    _handle_composer_action(composer_action)

    # Keep a single submit path at the end of the run.
    if request_in_flight and queued_prompt and response_placeholder is not None:
        payload_messages = _build_messages_payload(st.session_state.messages, queued_prompt)

        try:
            resp = api_client.chat(payload_messages, active_user_id)
            data = safe_json(resp)
            if resp.status_code != 200:
                assistant_content = format_http_error(resp, data)
                assistant_sources: list[dict] = []
            else:
                assistant_content = extract_assistant_content(data)
                assistant_sources = extract_assistant_sources(data)
                if not assistant_content:
                    assistant_content = (
                        "The assistant returned an unexpected response format. "
                        "Please retry or restart the demo services with run_demo.ps1."
                    )
                    assistant_sources = []
        except requests.RequestException as exc:
            assistant_content = (
                f"The assistant service is currently unavailable: {exc}. "
                "Please start the demo services with run_demo.ps1 and try again."
            )
            assistant_sources = []

        st.session_state.messages.append({"role": "user", "content": queued_prompt})
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": assistant_content,
                "sources": assistant_sources,
            }
        )
        st.session_state.queued_prompt = ""
        st.session_state.request_in_flight = False

        _stream_assistant_response(
            response_placeholder,
            assistant_content,
            bot_avatar_data,
            sources=assistant_sources,
        )

        st.rerun()


if __name__ == "__main__":
    main()
