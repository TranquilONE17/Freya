import threading
import time

import numpy as np
import pytest

from freya.turn_gate import TurnGate
from freya.voice.listener import (
    BackgroundListener,
    UtteranceSegmenter,
    WakeFilter,
)


BLOCK = 0.05
BLOCK_SAMPLES = 100
LOUD = np.full((BLOCK_SAMPLES, 1), 0.1, dtype="float32")
QUIET = np.zeros((BLOCK_SAMPLES, 1), dtype="float32")


def make_segmenter(**overrides):
    settings = {
        "block_seconds": BLOCK,
        "start_level": 0.012,
        "stop_level": 0.009,
        "silence_seconds": 0.25,
        "pre_roll_seconds": 0.1,
        "min_seconds": 0.15,
        "max_seconds": 2.0,
    }
    settings.update(overrides)
    return UtteranceSegmenter(**settings)


def feed(segmenter, blocks):
    return [u for u in (segmenter.feed(b) for b in blocks) if u is not None]


def test_silence_produces_nothing():
    segmenter = make_segmenter()

    assert feed(segmenter, [QUIET] * 100) == []
    assert segmenter.recording is False


def test_utterance_ends_after_a_stretch_of_quiet():
    segmenter = make_segmenter()

    finished = feed(segmenter, [QUIET] * 5 + [LOUD] * 6 + [QUIET] * 5)

    # Two blocks of pre-roll, six of speech, five of trailing quiet.
    assert len(finished) == 1
    assert len(finished[0]) == (2 + 6 + 5) * BLOCK_SAMPLES
    assert segmenter.recording is False


def test_pre_roll_keeps_the_audio_just_before_speech():
    segmenter = make_segmenter()
    lead = np.full((BLOCK_SAMPLES, 1), 0.005, dtype="float32")

    finished = feed(segmenter, [QUIET] * 5 + [lead] * 2 + [LOUD] * 6 + [QUIET] * 5)

    assert np.allclose(finished[0][: 2 * BLOCK_SAMPLES], 0.005)


def test_short_pause_does_not_split_a_sentence():
    segmenter = make_segmenter()

    finished = feed(
        segmenter,
        [LOUD] * 4 + [QUIET] * 3 + [LOUD] * 4 + [QUIET] * 5,
    )

    assert len(finished) == 1


def test_two_sentences_are_separate_utterances():
    segmenter = make_segmenter()

    finished = feed(
        segmenter,
        [LOUD] * 4 + [QUIET] * 6 + [LOUD] * 4 + [QUIET] * 6,
    )

    assert len(finished) == 2


def test_a_click_is_discarded():
    segmenter = make_segmenter()

    assert feed(segmenter, [LOUD] * 2 + [QUIET] * 6) == []


def test_endless_noise_is_cut_at_the_maximum_length():
    segmenter = make_segmenter()

    finished = feed(segmenter, [LOUD] * 45)

    assert len(finished) == 1
    assert len(finished[0]) == 40 * BLOCK_SAMPLES


def test_reset_discards_a_recording_in_progress():
    segmenter = make_segmenter()

    feed(segmenter, [LOUD] * 5)
    assert segmenter.recording is True

    segmenter.reset()

    assert segmenter.recording is False
    assert feed(segmenter, [QUIET] * 6) == []


class ScriptedStream:
    """A microphone that plays back a list of blocks, then stays quiet."""

    def __init__(self, blocks):
        self._blocks = list(blocks)
        self.reads = 0
        self.fail_with = None
        self.drained = threading.Event()

    def __enter__(self):
        if self.fail_with:
            raise self.fail_with
        return self

    def __exit__(self, *exc):
        return False

    def read(self, blocksize):
        self.reads += 1
        if self._blocks:
            return self._blocks.pop(0), False
        self.drained.set()
        time.sleep(0.001)
        return QUIET, False


class Harness:
    def __init__(self, blocks, transcripts):
        self.stream = ScriptedStream(blocks)
        self.transcripts = list(transcripts)
        self.requests = []
        self.errors = []
        self.busy = False
        self.listener = BackgroundListener(
            open_stream=lambda: self.stream,
            blocksize=BLOCK_SAMPLES,
            segmenter=make_segmenter(),
            transcribe=self.transcribe,
            wake_filter=WakeFilter(lambda: ["freya"]),
            on_request=self.requests.append,
            is_busy=lambda: self.busy,
            on_error=self.errors.append,
            settle_seconds=0.0,
        )

    def transcribe(self, audio):
        item = self.transcripts.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def run(self):
        self.listener.start()
        assert self.stream.drained.wait(timeout=5)
        self.listener.stop()
        return self


SENTENCE = [LOUD] * 5 + [QUIET] * 6


def test_listener_passes_on_speech_addressed_to_freya():
    harness = Harness(
        SENTENCE * 3,
        [
            "Freya, what time is it?",
            "Turn that down, would you?",
            "Hey Freya tell me a joke",
        ],
    ).run()

    assert harness.requests == ["what time is it?", "tell me a joke"]
    assert harness.errors == []


def test_listener_ignores_the_microphone_while_freya_is_busy():
    harness = Harness(SENTENCE, ["Freya, what time is it?"])
    harness.busy = True

    harness.run()

    # Nothing was even transcribed.
    assert harness.requests == []
    assert harness.transcripts == ["Freya, what time is it?"]


def test_listener_ignores_the_microphone_while_muted():
    harness = Harness(SENTENCE, ["Freya, what time is it?"])
    harness.listener.mute()

    harness.run()

    assert harness.listener.muted is True
    assert harness.requests == []
    assert harness.transcripts == ["Freya, what time is it?"]


def test_request_is_dropped_if_freya_became_busy_during_transcription():
    harness = Harness(SENTENCE, [])

    def transcribe(audio):
        harness.busy = True
        return "Freya, what time is it?"

    harness.listener._transcribe = transcribe
    harness.run()

    assert harness.requests == []


def test_transcription_failure_is_reported_and_listening_continues():
    harness = Harness(
        SENTENCE * 2,
        [RuntimeError("model unloaded"), "Freya, are you there?"],
    ).run()

    assert harness.requests == ["are you there?"]
    assert len(harness.errors) == 1
    assert "model unloaded" in harness.errors[0]


def test_microphone_failure_stops_listening_without_raising():
    harness = Harness([], [])
    harness.stream.fail_with = OSError("device unplugged")

    harness.listener.start()
    harness.listener.stop()

    assert harness.listener.running is False
    assert "device unplugged" in harness.errors[0]
    assert "Typing still works" in harness.errors[0]


def test_turn_gate_lets_spoken_turns_run_only_while_waiting_for_input(
    monkeypatch,
):
    gate = TurnGate()
    seen = []

    def fake_input(prompt):
        # The keyboard is waiting: a spoken turn can run now.
        with gate.spoken_turn() as acquired:
            seen.append(("during input", acquired, gate.busy()))
        return "hello"

    monkeypatch.setattr("builtins.input", fake_input)

    assert gate.busy() is False
    assert gate.read_line("You: ") == "hello"

    # A typed turn is now being handled: a spoken turn must not start.
    assert gate.busy() is True
    with gate.spoken_turn() as acquired:
        seen.append(("during typed turn", acquired, gate.busy()))

    # Asking for the next line ends the typed turn.
    assert gate.read_line("You: ") == "hello"
    gate.close()

    assert gate.busy() is False
    assert seen == [
        ("during input", True, True),
        ("during typed turn", False, True),
        ("during input", True, True),
    ]
    gate.close()


def test_turn_gate_is_released_when_input_is_interrupted(monkeypatch):
    gate = TurnGate()

    def interrupted(prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", interrupted)

    with pytest.raises(KeyboardInterrupt):
        gate.read_line("You: ")

    assert gate.busy() is False
    gate.close()
    assert gate.busy() is False
