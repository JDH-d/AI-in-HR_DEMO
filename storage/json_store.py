from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from storage.text_store import write_text


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=True, indent=2))
