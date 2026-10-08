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
    # A finished image is part of the conversation: it is shown in the
    # chat where it was asked for, as well as in the gallery.
    "image_ready",
}


class EventBus:
    """
    Tells every interested part of Freya what is happening: who said
    what, what she is replying, and what images she has made.

    The console prints as it always has. Anything else, such as the
    window, subscribes here instead of reading the console.

    Subscribers are called one event at a time, in the order events
    were published, while the bus is locked. That is what lets a new
    subscriber be given the conversation so far and then every later
    event exactly once. It also means a subscriber must be quick and
    must never wait on anything: one that needs to do slow work, such
    as writing to a socket, hands the event to a queue and does the
    work elsewhere.

    A subscriber that raises is dropped rather than allowed to break
    the turn that was publishing.
    """

    def __init__(self, history_limit=500):
        # Re-entrant, because a subscriber may itself publish.
        self._lock = threading.RLock()
        self._subscribers: List[Callable[[dict], None]] = []
        self._history = deque(maxlen=history_limit)

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def subscribe_with_history(
        self,
        callback: Callable[[dict], None],
    ) -> List[dict]:
        """
        Subscribe, and return the conversation up to that moment.

        The two happen as one step: every event is either in the
        returned history or delivered to the callback, never both and
        never neither.
        """
        with self._lock:
            self._subscribers.append(callback)

            return list(self._history)

    def unsubscribe(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def publish(self, event_type: str, **fields) -> dict:
        event = {"type": event_type, "time": time.time(), **fields}

        with self._lock:
            if event_type in CONVERSATION_EVENTS:
                self._history.append(event)

            for callback in list(self._subscribers):
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
