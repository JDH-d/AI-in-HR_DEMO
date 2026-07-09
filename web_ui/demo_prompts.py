from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import streamlit as st

DEMO_PROMPTS = [
    (
        "Quick Start",
        [
            "What can you help with?",
            "Hello",
            "Hi there",
        ],
    ),
    (
        "PTO and Leave",
        [
            "How far in advance should I request vacation?",
            "Can I request half-day PTO?",
            "Do company holidays reduce my PTO balance?",
            "I need vacation from 04/10 to 04/12",
        ],
    ),
    (
        "Payroll",
        [
            "How often are salaries paid?",
            "What happens if payday falls on a holiday?",
            "When should I update direct deposit information?",
            "What if my pay looks incorrect?",
        ],
    ),
    (
        "Benefits",
        [
            "When can I enroll in benefits?",
            "When do my deductions start?",
            "Can I add a dependent later?",
            "How do I know which medical plan is best?",
        ],
    ),
    (
        "Work Schedules",
        [
            "Can I change my regular working hours?",
            "Do remote employees still have core hours?",
            "What if I work extra hours without prior approval?",
            "How should I report being late or unexpectedly absent?",
        ],
    ),
    (
        "IT Support",
        [
            "How do I request VPN access?",
            "What should I do if I forget my password?",
            "What should I do if my laptop is lost?",
            "Who handles suspicious MFA prompts or phishing?",
        ],
    ),
    (
        "Unsupported Tests",
        [
            "Write me a poem about dragons.",
            "What's the weather in Los Angeles today?",
        ],
    ),
]


@dataclass(frozen=True)
class DemoPromptsAction:
    kind: str = "none"
    prompt: str = ""


def iter_demo_prompts(prompt_groups: Iterable[tuple[str, list[str]]]) -> list[str]:
    prompts: list[str] = []
    for _, items in prompt_groups:
        prompts.extend(items)
    return prompts


def render_demo_prompt_styles() -> None:
    st.markdown(
        """
        <style>
        .st-key-demo_prompts_shell {
            margin-top: 0.65rem;
            margin-bottom: 0.75rem;
        }

        .st-key-demo_prompts_panel {
            border: 1px solid #313949;
            background: rgba(15, 21, 31, 0.97);
            border-radius: 22px;
            padding: 1rem 1rem 0.85rem 1rem;
            box-shadow: 0 18px 34px rgba(7, 11, 18, 0.18);
        }

        .st-key-demo_prompts_panel [data-testid="stVerticalBlock"] {
            gap: 0.6rem;
        }

        .st-key-demo_prompts_panel [data-testid="stButton"] {
            margin-bottom: 0.1rem;
        }

        .st-key-demo_prompts_panel button {
            min-height: 3rem;
            border-radius: 999px !important;
            border: 1px solid #394255 !important;
            background: rgba(20, 25, 35, 0.9) !important;
            color: #eff4fb !important;
            white-space: normal !important;
            line-height: 1.35 !important;
        }

        .st-key-demo_prompts_panel button:hover {
            border-color: #5a6e90 !important;
            background: rgba(31, 39, 54, 0.96) !important;
        }

        .demo-prompts-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 12px;
            margin-bottom: 0.25rem;
        }

        .demo-prompts-title {
            font-size: 0.92rem;
            font-weight: 700;
            color: #e5edf9;
        }

        .demo-prompts-copy {
            color: #aab6c9;
            font-size: 0.92rem;
            line-height: 1.45;
            margin-bottom: 0.35rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_demo_prompts(prompt_groups: list[tuple[str, list[str]]]) -> DemoPromptsAction:
    with st.container(key="demo_prompts_shell"):
        with st.container(key="demo_prompts_panel"):
            header_col, close_col = st.columns([12, 1], gap="small", vertical_alignment="center")
            with header_col:
                st.markdown(
                    """
                    <div class="demo-prompts-header">
                        <div class="demo-prompts-title">Demo Prompts</div>
                    </div>
                    <div class="demo-prompts-copy">
                        Reuse a prepared prompt to demo policy answers, workflows, greetings, and unsupported-question filtering.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with close_col:
                close_clicked = st.button(
                    "✕", key="demo_prompts_close", help="Close demo prompts", width="content"
                )

            if close_clicked:
                return DemoPromptsAction(kind="close")

            for section_index, (title, prompts) in enumerate(prompt_groups):
                st.markdown(f"**{title}**")
                columns = st.columns(2)
                for prompt_index, prompt in enumerate(prompts):
                    if columns[prompt_index % 2].button(
                        prompt,
                        key=f"demo_prompt_{section_index}_{prompt_index}",
                        help=prompt,
                        width="stretch",
                    ):
                        return DemoPromptsAction(kind="submit_demo", prompt=prompt)

    return DemoPromptsAction()
