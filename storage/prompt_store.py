from pathlib import Path

from storage.text_store import write_text


class PromptStore:
    def __init__(self, path: Path, default: str) -> None:
        self.path = path
        self.default = default

    def get(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8").strip() or self.default
        except FileNotFoundError:
            return self.default

    def save(self, text: str) -> None:
        write_text(self.path, text.strip())
