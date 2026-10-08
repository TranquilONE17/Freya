import itertools
from collections import deque
from typing import Callable, Deque, Dict, List, Optional


# Priorities. A new animation interrupts a running one on the same
# channel when its priority is equal or higher; otherwise it waits.
IDLE = 0
AMBIENT = 10
NORMAL = 50
USER = 80
SYSTEM = 100

PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"

FINISHED = (COMPLETED, CANCELLED, INTERRUPTED)

# How many animations may wait on one channel. Further ones are
# refused, so a flood of requests cannot build an endless backlog.
MAX_WAITING = 8


def ease(progress: float) -> float:
    """
    Smooth start and stop: 0 to 1, slow at both ends.
    """
    progress = min(max(progress, 0.0), 1.0)

    return progress * progress * (3.0 - 2.0 * progress)


class Animation:
    """
    One animation in progress: a change applied a little more on each
    frame until it is done.

    It does not block and does not run by itself; the Animator advances
    it. It can be cancelled at any moment, and it is told how it ended.

    channel   the part of the avatar it drives. Two animations on
              different channels run together; two on the same channel
              do not.
    duration  seconds. Zero means "apply at once".
    step      called with eased progress from 0 to 1.
    """

    _ids = itertools.count(1)

    def __init__(
        self,
        channel: str,
        duration: float,
        step: Callable[[float], None],
        priority: int = NORMAL,
        label: str = "",
        on_start: Optional[Callable[[], None]] = None,
        on_end: Optional[Callable[[str], None]] = None,
        loop: bool = False,
    ):
        self.id = next(Animation._ids)
        self.channel = channel
        self.duration = max(float(duration), 0.0)
        self.priority = priority
        self.label = label
        self.loop = loop
        self.state = PENDING
        self.elapsed = 0.0
        self._step = step
        self._on_start = on_start
        self._on_end = on_end

    @property
    def done(self) -> bool:
        return self.state in FINISHED

    def _begin(self) -> None:
        self.state = RUNNING

        if self._on_start is not None:
            self._on_start()

    def _advance(self, seconds: float) -> None:
        self.elapsed += seconds

        if self.loop:
            period = self.duration or 1.0
            self._step((self.elapsed % period) / period)
            return

        if self.duration <= 0 or self.elapsed >= self.duration:
            self._step(1.0)
            self._end(COMPLETED)
        else:
            self._step(ease(self.elapsed / self.duration))

    def _end(self, state: str) -> None:
        if self.done:
            return

        self.state = state

        if self._on_end is not None:
            self._on_end(state)


class Animator:
    """
    Runs animations, one per channel at a time, in priority order.

    Nothing here knows about time or drawing: whoever draws calls
    tick() with the seconds since the last frame, which also makes the
    whole thing exactly repeatable in tests.
    """

    def __init__(self, on_change: Optional[Callable[[Animation], None]] = None):
        self._running: Dict[str, Animation] = {}
        self._waiting: Dict[str, Deque[Animation]] = {}
        self._on_change = on_change

    def _changed(self, animation: Animation) -> None:
        if self._on_change is not None:
            self._on_change(animation)

    def _finish(self, animation: Animation, state: str) -> None:
        animation._end(state)
        self._changed(animation)

    def _start(self, animation: Animation) -> None:
        self._running[animation.channel] = animation
        animation._begin()
        self._changed(animation)

        if animation.duration <= 0 and not animation.loop:
            animation._advance(0.0)
            self._changed(animation)
            self._running.pop(animation.channel, None)
            self._start_next(animation.channel)

    def _start_next(self, channel: str) -> None:
        waiting = self._waiting.get(channel)

        if waiting and channel not in self._running:
            self._start(waiting.popleft())

    def play(self, animation: Animation) -> Animation:
        """
        Start an animation, or queue it behind a more important one.
        Returns the animation, whose `state` says what became of it.
        """
        current = self._running.get(animation.channel)

        if current is None:
            self._start(animation)
            return animation

        if animation.priority >= current.priority:
            self._running.pop(animation.channel)
            self._finish(current, INTERRUPTED)

            # What was waiting behind the old one is dropped too: it
            # was asked for before this more important request.
            for waiting in self._waiting.pop(animation.channel, ()):
                self._finish(waiting, CANCELLED)

            self._start(animation)
            return animation

        waiting = self._waiting.setdefault(animation.channel, deque())

        if len(waiting) >= MAX_WAITING:
            self._finish(animation, CANCELLED)
        else:
            waiting.append(animation)

        return animation

    def cancel(self, animation: Animation) -> bool:
        """
        Stop one animation where it is. Returns False when it had
        already finished.
        """
        if animation.done:
            return False

        if self._running.get(animation.channel) is animation:
            self._running.pop(animation.channel)
            self._finish(animation, CANCELLED)
            self._start_next(animation.channel)
            return True

        waiting = self._waiting.get(animation.channel)

        if waiting and animation in waiting:
            waiting.remove(animation)

        self._finish(animation, CANCELLED)

        return True

    def cancel_all(self, channel: Optional[str] = None, below: Optional[int] = None) -> int:
        """
        Cancel everything, or everything on one channel, or everything
        less important than `below`. Returns how many were cancelled.
        """
        cancelled = 0

        for name in [channel] if channel else list(
            set(self._running) | set(self._waiting)
        ):
            for animation in list(self._waiting.get(name, ())) + (
                [self._running[name]] if name in self._running else []
            ):
                if below is None or animation.priority < below:
                    cancelled += self.cancel(animation)

        return cancelled

    def find(self, animation_id) -> Optional[Animation]:
        for animation in self.active():
            if animation.id == animation_id:
                return animation

        return None

    def active(self) -> List[Animation]:
        return list(self._running.values()) + [
            animation
            for waiting in self._waiting.values()
            for animation in waiting
        ]

    def busy(self, ignore_loops=True) -> bool:
        """
        True while anything is moving. Looping idle motion does not
        count, so a renderer can slow down while only that is running.
        """
        return any(
            not (ignore_loops and animation.loop)
            for animation in self.active()
        )

    def tick(self, seconds: float) -> None:
        """
        Advance every running animation by a frame.
        """
        seconds = min(max(seconds, 0.0), 0.25)

        for channel, animation in list(self._running.items()):
            animation._advance(seconds)

            if animation.done:
                self._changed(animation)

                if self._running.get(channel) is animation:
                    self._running.pop(channel)

                self._start_next(channel)
