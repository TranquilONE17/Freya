import re
from difflib import SequenceMatcher
from typing import Iterable, Optional


# Words people put in front of a name when calling someone.
LEAD_IN_WORDS = {
    "hey",
    "hi",
    "hello",
    "ok",
    "okay",
    "yo",
    "so",
    "um",
    "uh",
    "and",
    "well",
}

MAX_LEAD_IN_WORDS = 2

# Speech recognition often spells a name slightly differently ("Freyja",
# "Fraya"). A heard word this close to a name counts as the name.
NAME_SIMILARITY = 0.8
MIN_FUZZY_LENGTH = 4

WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?", re.UNICODE)

MAX_NAME_LENGTH = 30


def normalize_name(name: str) -> str:
    """
    Reduce a wake name to lower-case words separated by single spaces.
    Raises ValueError when nothing usable is left.
    """
    words = [match.group(0).lower() for match in WORD.finditer(name or "")]
    normalized = " ".join(words)

    if not normalized:
        raise ValueError("A name needs at least one letter.")

    if len(normalized) > MAX_NAME_LENGTH:
        raise ValueError(
            f"A name can be at most {MAX_NAME_LENGTH} characters."
        )

    return normalized


def _same_word(heard: str, wanted: str) -> bool:
    if heard.endswith("'s"):
        heard = heard[:-2]

    if heard == wanted:
        return True

    if min(len(heard), len(wanted)) < MIN_FUZZY_LENGTH:
        return False

    # A different first sound is a different word ("prayer", "player").
    if heard[0] != wanted[0]:
        return False

    return (
        SequenceMatcher(None, heard, wanted).ratio()
        >= NAME_SIMILARITY
    )


def _matches_at(tokens, start, name_words) -> bool:
    if start < 0 or start + len(name_words) > len(tokens):
        return False

    return all(
        _same_word(tokens[start + offset][0], wanted)
        for offset, wanted in enumerate(name_words)
    )


def match_wake(transcript: str, names: Iterable[str]) -> Optional[str]:
    """
    Decide whether a heard sentence was addressed to Freya.

    Returns None when it was not. Otherwise returns what was said to
    her with the name removed, which is an empty string when only the
    name was spoken.

    The name must open the sentence (after at most a couple of words
    such as "hey" or "okay") or close it: "Freya, what time is it?" or
    "What time is it, Freya?". A name in the middle of a sentence is
    usually someone talking about her, not to her.
    """
    text = (transcript or "").strip()

    tokens = [
        (match.group(0).lower(), match.start(), match.end())
        for match in WORD.finditer(text)
    ]

    if not tokens:
        return None

    candidates = sorted(
        (normalize_name(name).split(" ") for name in names),
        key=len,
        reverse=True,
    )

    for name_words in candidates:
        for lead_in in range(MAX_LEAD_IN_WORDS + 1):
            if lead_in > len(tokens):
                break

            if any(
                token[0] not in LEAD_IN_WORDS
                for token in tokens[:lead_in]
            ):
                break

            if _matches_at(tokens, lead_in, name_words):
                end = tokens[lead_in + len(name_words) - 1][2]
                return text[end:].lstrip(" ,.!?:;-—").strip()

    for name_words in candidates:
        start = len(tokens) - len(name_words)

        if start > 0 and _matches_at(tokens, start, name_words):
            return text[: tokens[start][1]].rstrip(" ,.!?:;-—").strip()

    return None
