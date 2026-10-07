import threading
import time
from collections import deque
from typing import Callable, Optional

import numpy as np

from freya.voice.wake import match_wake


class UtteranceSegmenter:
    """
    Cuts a stream of microphone blocks into utterances.

    Recording starts when a block is louder than the start level and
    ends after a stretch of quiet. A little audio from before the
    start is kept, so the first syllable (usually the name) is not
    clipped.
    """

    def __init__(
        self,
        block_seconds: float,
        start_level: float,
        stop_level: float,
        silence_seconds: float,
        pre_roll_seconds: float = 0.4,
        min_seconds: float = 0.3,
        max_seconds: float = 30.0,
    ):
        self._block_seconds = block_seconds
        self._start_level = start_level
        self._stop_level = stop_level
        self._silence_seconds = silence_seconds
        self._min_seconds = min_seconds
        self._max_seconds = max_seconds

        self._pre_roll = deque(
            maxlen=max(1, round(pre_roll_seconds / block_seconds))
        )
        self.reset()

    def reset(self) -> None:
        """
        Forget anything heard so far.
        """
        self._pre_roll.clear()
        self._frames = []
        self._recording = False
        self._voiced = 0.0
        self._silence = 0.0

    @property
    def recording(self) -> bool:
        return self._recording

    def feed(self, block: np.ndarray) -> Optional[np.ndarray]:
        """
        Add one block. Returns the finished utterance when this block
        completes one, otherwise None.
        """
        level = float(np.sqrt(np.mean(np.square(block))))

        if not self._recording:
            if level < self._start_level:
                self._pre_roll.append(block.copy())
                return None

            self._recording = True
            self._frames = list(self._pre_roll)
            self._pre_roll.clear()

        self._frames.append(block.copy())

        if level < self._stop_level:
            self._silence += self._block_seconds
        else:
            self._silence = 0.0
            self._voiced += self._block_seconds

        length = len(self._frames) * self._block_seconds

        if (
            self._silence < self._silence_seconds
            and length < self._max_seconds
        ):
            return None

        frames, voiced = self._frames, self._voiced
        self.reset()

        # A click or a cough is not worth transcribing.
        if voiced < self._min_seconds:
            return None

        return np.concatenate(frames, axis=0)


class WakeFilter:
    """
    Decides which heard sentences are meant for Freya.

    A sentence counts when it is addressed to one of her names. Saying
    only the name gets her attention: the next sentence within the
    attention window counts without the name.
    """

    def __init__(
        self,
        names: Callable[[], list],
        attention_seconds: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._names = names
        self._attention_seconds = attention_seconds
        self._clock = clock
        self._attention_until = 0.0

    def check(self, transcript: str) -> Optional[str]:
        """
        Returns None when the sentence is not for Freya, an empty
        string when only her name was said, and otherwise what was
        said to her.
        """
        transcript = (transcript or "").strip()

        if not transcript:
            return None

        addressed = match_wake(transcript, self._names())

        if addressed is None:
            if self._clock() < self._attention_until:
                self._attention_until = 0.0
                return transcript

            return None

        if addressed == "":
            self._attention_until = (
                self._clock() + self._attention_seconds
            )
        else:
            self._attention_until = 0.0

        return addressed


class BackgroundListener:
    """
    Keeps the microphone open while Freya waits at the keyboard, and
    hands over what was said to her.

    Audio is ignored whenever is_busy() says Freya is speaking or
    working on a turn, so she does not answer herself. Speech that is
    not addressed to her is transcribed and then discarded.
    """

    def __init__(
        self,
        open_stream: Callable[[], object],
        blocksize: int,
        segmenter: UtteranceSegmenter,
        transcribe: Callable[[np.ndarray], str],
        wake_filter: WakeFilter,
        on_request: Callable[[str], None],
        is_busy: Callable[[], bool],
        on_error: Callable[[str], None] = print,
        settle_seconds: float = 0.5,
    ):
        self._open_stream = open_stream
        self._blocksize = blocksize
        self._segmenter = segmenter
        self._transcribe = transcribe
        self._wake_filter = wake_filter
        self._on_request = on_request
        self._is_busy = is_busy
        self._on_error = on_error
        self._settle_seconds = settle_seconds

        self._muted = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.running = False

    @property
    def muted(self) -> bool:
        return self._muted.is_set()

    def mute(self) -> None:
        self._muted.set()

    def unmute(self) -> None:
        self._muted.clear()

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="FreyaListener",
            daemon=True,
        )
        self.running = True
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run(self) -> None:
        try:
            with self._open_stream() as stream:
                self._listen(stream)
        except Exception as exc:
            self._on_error(
                "\n[Background listening stopped: "
                f"{exc}. Typing still works.]"
            )
        finally:
            self.running = False

    def _listen(self, stream) -> None:
        quiet_until = 0.0

        while not self._stop.is_set():
            block, _ = stream.read(self._blocksize)

            if self._muted.is_set() or self._is_busy():
                # Also wait a moment afterwards, for the tail of
                # Freya's own voice to die away.
                self._segmenter.reset()
                quiet_until = time.monotonic() + self._settle_seconds
                continue

            if time.monotonic() < quiet_until:
                continue

            utterance = self._segmenter.feed(block)

            if utterance is None:
                continue

            self.handle_utterance(utterance)

            # Whatever the microphone buffered meanwhile is stale.
            self._segmenter.reset()
            quiet_until = time.monotonic() + self._settle_seconds

    def handle_utterance(self, utterance: np.ndarray) -> None:
        try:
            transcript = self._transcribe(utterance)
        except Exception as exc:
            self._on_error(
                f"\n[Could not transcribe speech: {exc}]"
            )
            return

        request = self._wake_filter.check(transcript)

        if request is None:
            return

        # Freya may have started speaking or a typed turn may have
        # begun while this was being transcribed.
        if self._muted.is_set() or self._is_busy():
            return

        self._on_request(request)
