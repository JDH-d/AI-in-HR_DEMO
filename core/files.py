from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

_write_lock = threading.RLock()


def atomic_write_text(path: Path, content: str) -> None:
    """Replace a text file atomically without sharing a fixed temporary path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary_path.replace(path)
        finally:
            temporary_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any, *, indent: int | None = None) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=True, indent=indent))
