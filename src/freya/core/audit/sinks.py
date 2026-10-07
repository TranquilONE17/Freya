import json
import os
from pathlib import Path
from typing import Optional


class FileCheckpointSink:
    """
    Appends audit checkpoints to a file, one JSON object per line.

    A checkpoint only helps detect tampering when this file lives
    somewhere the machine running Freya cannot rewrite, such as an
    append-only share on another host. Only the chain hash is written,
    never audit content.
    """

    def __init__(self, path):
        self.path = Path(path)

    @property
    def name(self) -> str:
        return f"file:{self.path}"

    def write(self, checkpoint: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(checkpoint, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def read_latest(self) -> Optional[dict]:
        """
        Return the most recent checkpoint, or None when there is none.
        """
        if not self.path.exists():
            return None

        latest = None

        with open(self.path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    latest = json.loads(line)

        return latest
