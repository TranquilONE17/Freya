import json
import os
import threading
from pathlib import Path
from typing import List

from freya.voice.wake import normalize_name


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
SETTINGS_PATH = DATA_DIR / "freya_settings.json"

DEFAULT_WAKE_NAMES = ["freya"]


class Settings:
    """
    Small preferences the owner changes while Freya is running, kept in
    a JSON file next to the databases.

    Unreadable or missing settings fall back to the defaults rather
    than stopping Freya.
    """

    def __init__(self, path=SETTINGS_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._wake_names = list(DEFAULT_WAKE_NAMES)
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return

        stored = (
            data.get("wake_names")
            if isinstance(data, dict)
            else None
        )

        if not isinstance(stored, list):
            return

        names = []

        for name in stored:
            if not isinstance(name, str):
                continue

            try:
                name = normalize_name(name)
            except ValueError:
                continue

            if name not in names:
                names.append(name)

        if names:
            self._wake_names = names

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"wake_names": self._wake_names}, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @property
    def wake_names(self) -> List[str]:
        with self._lock:
            return list(self._wake_names)

    def add_wake_name(self, name: str) -> str:
        """
        Add a name Freya answers to. Returns the stored form.
        Raises ValueError for an unusable or duplicate name.
        """
        name = normalize_name(name)

        with self._lock:
            if name in self._wake_names:
                raise ValueError(f"I already answer to {name}.")

            self._wake_names.append(name)
            self._save()

        return name

    def remove_wake_name(self, name: str) -> str:
        """
        Remove a name. The last remaining name cannot be removed,
        because Freya would then never respond to speech.
        """
        name = normalize_name(name)

        with self._lock:
            if name not in self._wake_names:
                raise ValueError(f"I don't answer to {name}.")

            if len(self._wake_names) == 1:
                raise ValueError(
                    "That is the only name I answer to. "
                    "Add another before removing it."
                )

            self._wake_names.remove(name)
            self._save()

        return name
