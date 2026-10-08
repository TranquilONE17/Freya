import threading
from contextlib import contextmanager


class TurnGateClosed(Exception):
    """
    A turn was asked for after Freya began shutting down.
    """


class TurnGate:
    """
    Makes sure Freya handles one turn at a time, whether it was typed
    or spoken.

    The keyboard loop holds the gate from the moment a line is entered
    until it asks for the next one. A spoken turn takes the gate only
    while the keyboard loop is waiting for input.

    Once closed, the gate lets no further turn begin, so that shutdown
    can wait for the turn in progress and then safely close what turns
    depend on.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._held_by_keyboard = False
        self._closed = False

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
        """
        Let no further turn begin. A turn already running carries on;
        `drain` waits for it.
        """
        self._closed = True
        self._release_keyboard()

    def drain(self, timeout: float) -> bool:
        """
        After `close`, wait for the turn in progress to finish. Returns
        False when it is still running after `timeout` seconds.
        """
        if not self._lock.acquire(timeout=timeout):
            return False

        self._lock.release()

        return True

    def _release_keyboard(self) -> None:
        if self._held_by_keyboard:
            self._held_by_keyboard = False
            self._lock.release()

    @contextmanager
    def turn(self):
        """
        Take the gate for a turn asked for from the window, waiting
        for any turn already in progress to finish. Raises
        TurnGateClosed when Freya is shutting down.
        """
        with self._lock:
            if self._closed:
                raise TurnGateClosed("Freya is shutting down.")

            yield

    @contextmanager
    def spoken_turn(self):
        """
        Take the gate for a spoken turn. Yields False, without
        waiting, when a typed turn is already being handled or Freya
        is shutting down.
        """
        acquired = self._lock.acquire(blocking=False)

        if acquired and self._closed:
            self._lock.release()
            acquired = False

        try:
            yield acquired
        finally:
            if acquired:
                self._lock.release()
