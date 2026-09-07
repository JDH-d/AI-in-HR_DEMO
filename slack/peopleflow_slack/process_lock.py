"""Prevent competing Socket Mode receivers from using the same local state."""

import hashlib
import os
import tempfile
from pathlib import Path


def installation_lock_path(team_id: str, employee_user_id: str) -> Path:
    """All local checkouts share one receiver for an installation, without storing tokens."""
    identity = hashlib.sha256(f"{team_id}:{employee_user_id}".encode()).hexdigest()
    return Path(tempfile.gettempdir()) / "peopleflow-slack-locks" / f"{identity}.lock"


class ProcessLock:
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise ValueError(
                "PeopleFlow Slack is already running for this installation or state directory. "
                "Stop the existing instance before starting another one."
            ) from exc
        return self

    def __exit__(self, *_):
        if self.file:
            self.file.close()  # OS releases the lock even after a crash.
            self.file = None
