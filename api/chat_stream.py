import json
from collections.abc import Iterator


def stream_events(content: str, *, start: dict, complete: dict) -> Iterator[str]:
    # The complete response is committed before streaming; disconnecting never loses it.
    yield json.dumps({"type": "start", **start}) + "\n"
    for position in range(0, len(content), 32):
        yield json.dumps({"type": "token", "content": content[position : position + 32]}) + "\n"
    yield json.dumps({"type": "complete", **complete}) + "\n"
