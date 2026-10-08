import pytest

from freya.voice.listener import WakeFilter
from freya.voice.wake import match_wake, normalize_name


NAMES = ["freya"]


@pytest.mark.parametrize(
    "heard, request_text",
    [
        ("Freya, how hot is my CPU?", "how hot is my CPU?"),
        ("freya what time is it", "what time is it"),
        ("Hey Freya, what's my RAM usage?", "what's my RAM usage?"),
        ("Okay, Freya. Tell me a joke.", "Tell me a joke."),
        ("Um, hey Freya how are you", "how are you"),
        ("FREYA! Stop.", "Stop."),
        ("Freya — are you there?", "are you there?"),
        # The name can close the sentence instead.
        ("What time is it, Freya?", "What time is it"),
        ("How hot is the GPU Freya", "How hot is the GPU"),
        # Only the name.
        ("Freya.", ""),
        ("Hey Freya", ""),
        ("  freya  ", ""),
    ],
)
def test_sentences_addressed_to_her(heard, request_text):
    assert match_wake(heard, NAMES) == request_text


@pytest.mark.parametrize(
    "heard",
    [
        "Freyja, what time is it?",
        "Fraya what time is it",
        "Freia, what time is it?",
        "Hey Frea, what time is it",
        "Freya's what time is it",
    ],
)
def test_speech_recognition_misspellings_still_count(heard):
    assert match_wake(heard, NAMES) is not None


@pytest.mark.parametrize(
    "heard",
    [
        "",
        "   ",
        "...",
        "What time is it?",
        "Turn the volume up.",
        # Talking about her, not to her.
        "I told Freya about it yesterday.",
        "Did you ask Freya or did you look it up yourself?",
        # Too many words before the name to be calling her.
        "I think that maybe Freya should check",
        # Similar-sounding words that are not her name.
        "Free, what time is it",
        "Friday, what time is it",
        "Prayer, what time is it",
        "Fred, how are you",
        "Player one, are you ready",
    ],
)
def test_other_speech_is_ignored(heard):
    assert match_wake(heard, NAMES) is None


def test_nicknames_and_multi_word_names():
    names = ["freya", "computer", "hey you", "f"]

    assert match_wake("Computer, status report", names) == "status report"
    assert match_wake("hey you what's up", names) == "what's up"
    assert match_wake("What's the time, computer?", names) == "What's the time"
    # A very short name must match exactly.
    assert match_wake("F, status", names) == "status"
    assert match_wake("If status", names) is None
    assert match_wake("Jarvis, status report", names) is None


def test_longer_name_wins_over_a_shorter_one():
    names = ["freya", "freya dear"]

    assert match_wake("Freya dear, are you there", names) == "are you there"


@pytest.mark.parametrize(
    "raw, normalized",
    [
        ("Freya", "freya"),
        ("  Hey   You ", "hey you"),
        ("Frey-Frey!", "frey frey"),
        ("O'Brien", "o'brien"),
    ],
)
def test_normalize_name(raw, normalized):
    assert normalize_name(raw) == normalized


@pytest.mark.parametrize("raw", ["", "   ", "123", "!!!", None, "x" * 31])
def test_normalize_name_rejects_unusable_names(raw):
    with pytest.raises(ValueError):
        normalize_name(raw)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def wake(clock):
    return WakeFilter(lambda: ["freya"], attention_seconds=10.0, clock=clock)


def test_filter_passes_addressed_speech_and_drops_the_rest(wake):
    assert wake.check("Freya, what time is it?") == "what time is it?"
    assert wake.check("What time is it?") is None
    assert wake.check("") is None
    assert wake.check(None) is None


def test_name_alone_gets_her_attention_for_one_sentence(wake, clock):
    assert wake.check("Freya.") == ""

    clock.now += 4
    assert wake.check("What time is it?") == "What time is it?"

    # Attention covers one sentence, not everything after it.
    assert wake.check("And the weather?") is None


def test_attention_expires(wake, clock):
    assert wake.check("Freya") == ""

    clock.now += 10.5

    assert wake.check("What time is it?") is None


def test_addressed_sentence_does_not_open_an_attention_window(wake):
    assert wake.check("Freya, tell me a joke") == "tell me a joke"
    assert wake.check("That was funny") is None


def test_filter_uses_the_current_name_list(clock):
    names = ["freya"]
    wake = WakeFilter(lambda: names, clock=clock)

    assert wake.check("Computer, status") is None

    names.append("computer")

    assert wake.check("Computer, status") == "status"
