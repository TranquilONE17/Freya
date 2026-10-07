import threading
from contextlib import contextmanager


class TurnGate:
    """
    Makes sure Freya handles one turn at a time, whether it was typed
    or spoken.

    The keyboard loop holds the gate from the moment a line is entered
    until it asks for the next one. A spoken turn takes the gate only
    while the keyboard loop is waiting for input.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._held_by_keyboard = False

    def busy(self) -> bool:
        return self._lock.locked()

    def read_line(self, prompt: str) -> str:
        """
        Wait for a typed line. Spoken turns may run while this waits.
        """
        self._release_keyboard()

        line = input(prompt)

        self._lock.acquire()
        self._held_by_keyboard = True

        return line

    def close(self) -> None:
        self._release_keyboard()

    def _release_keyboard(self) -> None:
        if self._held_by_keyboard:
            self._held_by_keyboard = False
            self._lock.release()

    @contextmanager
    def turn(self):
        """
        Take the gate for a turn asked for from the window, waiting
        for any turn already in progress to finish.
        """
        with self._lock:
            yield

    @contextmanager
    def spoken_turn(self):
        """
        Take the gate for a spoken turn. Yields False, without
        waiting, when a typed turn is already being handled.
        """
        acquired = self._lock.acquire(blocking=False)

        try:
            yield acquired
        finally:
            if acquired:
                self._lock.release()
