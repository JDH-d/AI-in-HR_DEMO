from api.chat_adapter import to_chat_query
from api.v1_schemas import V1ChatRequest


def test_zero_similarity_threshold_is_preserved() -> None:
    payload = V1ChatRequest(
        messages=[{"role": "user", "content": "Show every potentially relevant source."}],
        min_similarity=0,
    )

    assert to_chat_query(payload).min_similarity == 0
