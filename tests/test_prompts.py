from types import SimpleNamespace

import pytest

from rag.prompts import build_general_prompt, build_rag_prompt


@pytest.mark.parametrize("grounded", [False, True])
def test_follow_up_preserves_history_with_role_specific_responses_content(grounded: bool) -> None:
    messages = [
        SimpleNamespace(role="user", content="How do I request leave?"),
        SimpleNamespace(role="assistant", content="Submit a request for manager review."),
        SimpleNamespace(role="user", content="Can you approve it?"),
    ]
    sources = [
        {
            "title": "Leave policy",
            "section": "Approval",
            "version": "1",
            "text": "Only a manager can approve leave.",
        }
    ]

    prompt = (
        build_rag_prompt("en", messages, sources)
        if grounded
        else build_general_prompt("en", messages)
    )

    assert [message["role"] for message in prompt] == ["system", "user", "assistant", "user"]
    assert [message["content"][0]["type"] for message in prompt] == [
        "input_text",
        "input_text",
        "output_text",
        "input_text",
    ]
    assert prompt[1]["content"][0]["text"] == messages[0].content
    assert prompt[2]["content"][0]["text"] == messages[1].content
    assert prompt[3]["content"][0]["text"].endswith(messages[2].content)
    if grounded:
        assert sources[0]["text"] in prompt[3]["content"][0]["text"]
