import threading
import time
from collections import deque
from typing import Callable, List


# Events that make up the conversation, replayed to a window that opens
# after the conversation has started.
CONVERSATION_EVENTS = {
    "user",
    "assistant_start",
    "assistant_chunk",
    "assistant_end",
    "notice",
}


class EventBus:
    """
    Tells every interested part of Freya what is happening: who said
    what, what she is replying, and what images she has made.

    The console prints as it always has. Anything else, such as the
    window, subscribes here instead of reading the console.

    A subscriber that raises is dropped rather than allowed to break
    the turn that was publishing.
    """

    def __init__(self, history_limit=500):
        self._lock = threading.Lock()
        self._subscribers: List[Callable[[dict], None]] = []
        self._history = deque(maxlen=history_limit)

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def publish(self, event_type: str, **fields) -> dict:
        event = {"type": event_type, "time": time.time(), **fields}

        with self._lock:
            if event_type in CONVERSATION_EVENTS:
                self._history.append(event)

            subscribers = list(self._subscribers)

        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                self.unsubscribe(callback)

        return event

    def history(self) -> List[dict]:
        """
        The conversation so far, oldest first.
        """
        with self._lock:
            return list(self._history)
