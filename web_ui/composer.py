from __future__ import annotations

from dataclasses import dataclass

import streamlit as st
import streamlit.components.v1 as components


@dataclass(frozen=True)
class ComposerAction:
    kind: str = "none"
    prompt: str = ""


def _queue_manual_submit() -> None:
    prompt = str(st.session_state.get("composer_draft", "")).strip()
    if not prompt:
        return

    # Update the request state before the next rerun begins rendering so the
    # idle composer is not painted one extra time during submit.
    st.session_state.queued_prompt = prompt
    st.session_state.drawer_open = False
    st.session_state.request_in_flight = True


def render_composer_styles() -> None:
    st.markdown(
        """
        <style>
        .st-key-composer_shell {
            margin-top: 0.9rem;
        }

        .st-key-composer_bar {
            border: 1px solid #343c4c;
            background: rgba(38, 39, 46, 0.96);
            border-radius: 28px;
            padding: 0.35rem 0.45rem;
            box-shadow: 0 18px 34px rgba(8, 12, 20, 0.16);
        }

        .st-key-composer_bar [data-testid="stHorizontalBlock"] {
            align-items: center;
            gap: 0.55rem;
            flex-wrap: nowrap;
        }

        .st-key-composer_bar [data-testid="stTextInput"],
        .st-key-composer_bar [data-testid="stButton"] {
            margin-bottom: 0;
        }

        .st-key-composer_bar [data-testid="stTextInput"] {
            display: flex;
            align-items: center;
            flex: 1 1 auto;
            min-width: 0;
        }

        .st-key-composer_bar [data-testid="stButton"] {
            flex: 0 0 auto;
        }

        .st-key-composer_bar [data-testid="stForm"] {
            width: 100%;
        }

        .st-key-composer_bar form {
            width: 100%;
        }

        .st-key-composer_bar [data-testid="stTextInputRootElement"],
        .st-key-composer_bar [data-testid="stTextInputRootElement"] [data-baseweb="input"] {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            height: 3.2rem !important;
            min-height: 3.2rem !important;
        }

        .st-key-composer_bar [data-testid="stTextInputRootElement"] > div,
        .st-key-composer_bar [data-testid="stTextInputRootElement"] [data-baseweb="input"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            border: none !important;
            background: transparent !important;
            box-shadow: none !important;
            height: 3.2rem !important;
            min-height: 3.2rem !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
        }

        .st-key-composer_bar [data-testid="stTextInputRootElement"],
        .st-key-composer_bar [data-testid="stTextInputRootElement"]:hover,
        .st-key-composer_bar [data-testid="stTextInputRootElement"]:focus,
        .st-key-composer_bar [data-testid="stTextInputRootElement"]:focus-within,
        .st-key-composer_bar [data-testid="stTextInputRootElement"][aria-invalid="true"],
        .st-key-composer_bar [data-testid="stTextInputRootElement"][data-invalid="true"],
        .st-key-composer_bar [data-testid="stTextInputRootElement"] [data-baseweb="input"],
        .st-key-composer_bar [data-testid="stTextInputRootElement"] [data-baseweb="input"]:hover,
        .st-key-composer_bar [data-testid="stTextInputRootElement"] [data-baseweb="input"]:focus,
        .st-key-composer_bar [data-testid="stTextInputRootElement"] [data-baseweb="input"]:focus-within,
        .st-key-composer_bar [data-testid="stTextInputRootElement"] [data-baseweb="input"][aria-invalid="true"],
        .st-key-composer_bar [data-testid="stTextInputRootElement"] > div,
        .st-key-composer_bar [data-testid="stTextInputRootElement"] > div:hover,
        .st-key-composer_bar [data-testid="stTextInputRootElement"] > div:focus,
        .st-key-composer_bar [data-testid="stTextInputRootElement"] > div:focus-within {
            border-color: transparent !important;
            outline: none !important;
            box-shadow: none !important;
        }

        .st-key-composer_bar input {
            color: #f2f5fb !important;
            background: transparent !important;
            height: 3.2rem !important;
            min-height: 3.2rem !important;
            font-size: 1rem !important;
            line-height: normal !important;
            padding: 0 0.75rem !important;
            border: none !important;
            outline: none !important;
            box-shadow: none !important;
            transform: translateY(-1px);
        }

        .st-key-composer_bar input:hover,
        .st-key-composer_bar input:focus,
        .st-key-composer_bar input:focus-visible,
        .st-key-composer_bar input:invalid,
        .st-key-composer_bar input[aria-invalid="true"] {
            border: none !important;
            outline: none !important;
            box-shadow: none !important;
        }

        .st-key-composer_bar [data-testid="InputInstructions"],
        .st-key-composer_bar [data-testid="stTextInput"] [aria-live],
        .st-key-composer_bar [data-testid="stTextInput"] [id$="-instructions"] {
            display: none !important;
        }

        .st-key-composer_bar input:disabled {
            color: #f2f5fb !important;
            -webkit-text-fill-color: #f2f5fb !important;
            opacity: 1 !important;
        }

        .st-key-composer_bar input::placeholder {
            color: #b7bdc8 !important;
        }

        .st-key-composer_bar button {
            width: 3rem;
            min-width: 3rem;
            min-height: 3rem;
            border-radius: 999px !important;
            border: 1px solid #495062 !important;
            background: rgba(18, 24, 34, 0.18) !important;
            color: #f4f7fb !important;
            box-shadow: none !important;
            font-weight: 600 !important;
            padding: 0 !important;
        }

        .st-key-composer_bar button:hover {
            border-color: #6d7fa0 !important;
            background: rgba(52, 63, 81, 0.58) !important;
        }

        .st-key-composer_bar button:disabled {
            opacity: 1 !important;
            cursor: default !important;
        }

        .st-key-composer_bar [data-testid="column"]:last-child button {
            background: linear-gradient(135deg, #1d4ed8, #2563eb 58%, #3b82f6) !important;
            border-color: #78a8ff !important;
        }

        .st-key-composer_bar [data-testid="column"]:last-child button:hover {
            background: linear-gradient(135deg, #2157ec, #3170ff 58%, #4c8bff) !important;
        }

        .st-key-composer_bar [data-testid="column"]:first-child button {
            font-size: 1.45rem !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _disable_composer_spellcheck() -> None:
    components.html(
        """
        <script>
        const applyComposerInputAttributes = () => {
            const doc = window.parent.document;
            const input = doc.querySelector('.st-key-composer_bar input');
            if (!input) {
                return false;
            }
            input.setAttribute('spellcheck', 'false');
            input.setAttribute('autocomplete', 'off');
            input.setAttribute('autocorrect', 'off');
            input.setAttribute('autocapitalize', 'off');
            return true;
        };

        applyComposerInputAttributes();
        setTimeout(applyComposerInputAttributes, 100);
        setTimeout(applyComposerInputAttributes, 500);

        const observer = new MutationObserver(applyComposerInputAttributes);
        observer.observe(window.parent.document.body, {
            childList: true,
            subtree: true,
        });
        </script>
        """,
        height=0,
        width=0,
    )


def render_composer(*, disabled: bool) -> ComposerAction:
    _disable_composer_spellcheck()
    with st.container(key="composer_shell"):
        with st.container(key="composer_bar", horizontal=True, vertical_alignment="center", gap="small"):
            toggle_col, form_col = st.columns([1, 12], gap="small", vertical_alignment="center")

            with toggle_col:
                toggle_clicked = st.button(
                    "＋",
                    key="composer_toggle",
                    help="Open demo prompts",
                    width="content",
                    disabled=disabled,
                )

            with form_col:
                with st.form("composer_form", clear_on_submit=False, enter_to_submit=not disabled, border=False):
                    input_col, send_col = st.columns([12, 1], gap="small", vertical_alignment="center")
                    with input_col:
                        st.text_input(
                            "Ask a company policy question",
                            key="composer_draft",
                            placeholder="Ask a company policy question",
                            label_visibility="collapsed",
                            disabled=disabled,
                        )
                    with send_col:
                        st.form_submit_button(
                            "↑",
                            key="composer_send",
                            help="Send message",
                            width="content",
                            disabled=disabled,
                            on_click=_queue_manual_submit,
                        )

    if toggle_clicked:
        return ComposerAction(kind="toggle_drawer")

    return ComposerAction()
