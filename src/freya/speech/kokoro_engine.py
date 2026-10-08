import importlib.util
import threading
from typing import Dict, List

import numpy as np

from freya.speech.engines import (
    ROLE_BLEND,
    ROLE_PRESET,
    STATUS_READY,
    EngineInfo,
    SpeechEngine,
    SpeechError,
)


ENGINE_ID = "kokoro"
REPO_ID = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24000

MIN_SPEED = 0.5
MAX_SPEED = 2.0

MAX_BLEND_VOICES = 4

# Languages by Kokoro's one-letter code. `needs` names Python modules a
# language cannot work without; the ones listed are not part of Freya's
# standard install.
LANGUAGES = {
    "a": {"name": "English (American)", "needs": ()},
    "b": {"name": "English (British)", "needs": ()},
    "e": {"name": "Spanish", "needs": ()},
    "f": {"name": "French", "needs": ()},
    "h": {"name": "Hindi", "needs": ()},
    "i": {"name": "Italian", "needs": ()},
    "p": {"name": "Portuguese (Brazilian)", "needs": ()},
    "j": {"name": "Japanese", "needs": ("pyopenjtalk",)},
    "z": {"name": "Mandarin Chinese", "needs": ("jieba", "pypinyin")},
}

# The voices supplied with Kokoro-82M v1.0. The first letter is the
# language and the second is f or m.
VOICES = {
    "a": [
        "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica",
        "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah",
        "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir",
        "am_liam", "am_michael", "am_onyx", "am_puck", "am_santa",
    ],
    "b": [
        "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
        "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    ],
    "e": ["ef_dora", "em_alex", "em_santa"],
    "f": ["ff_siwis"],
    "h": ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"],
    "i": ["if_sara", "im_nicola"],
    "p": ["pf_dora", "pm_alex", "pm_santa"],
    "j": [
        "jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro",
        "jm_kumo",
    ],
    "z": [
        "zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi",
        "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
    ],
}

ALL_VOICES = {voice for voices in VOICES.values() for voice in voices}


def voice_label(voice: str) -> str:
    gender = "female" if voice[1] == "f" else "male"

    return f"{voice[3:].replace('_', ' ').title()} ({gender})"


def language_available(code: str) -> bool:
    return all(
        importlib.util.find_spec(module) is not None
        for module in LANGUAGES[code]["needs"]
    )


def _speed(value) -> float:
    try:
        speed = float(value)
    except (TypeError, ValueError):
        raise SpeechError("Speed must be a number.")

    if not MIN_SPEED <= speed <= MAX_SPEED:
        raise SpeechError(
            f"Speed must be between {MIN_SPEED} and {MAX_SPEED}."
        )

    return round(speed, 2)


def _language(value) -> str:
    if value not in LANGUAGES:
        raise SpeechError("That language is not one Kokoro supports.")

    if not language_available(value):
        raise SpeechError(
            f"{LANGUAGES[value]['name']} needs extra language "
            "packages that are not installed."
        )

    return value


class KokoroEngine(SpeechEngine):
    """
    Kokoro: lightweight speech using the voices it ships with.

    It can also average several of its own voices into a blend. A blend
    is a mix of existing supplied voices. It is not a clone of anyone's
    recording, and it is not a voice designed from a description.
    """

    id = ENGINE_ID

    def __init__(self, pipeline_factory=None, shared_model=None):
        self._pipeline_factory = pipeline_factory
        self._pipelines: Dict[str, object] = {}
        # Freya's own voice already has the model loaded; reuse it
        # instead of loading a second copy.
        self._model = shared_model
        self._lock = threading.Lock()

    def info(self) -> EngineInfo:
        return EngineInfo(
            id=ENGINE_ID,
            name="Kokoro",
            summary=(
                "Lightweight speech using the voices supplied with it."
            ),
            roles=(ROLE_PRESET, ROLE_BLEND),
            status=STATUS_READY,
            detail="Runs on this computer.",
            controls={
                "speed": {
                    "min": MIN_SPEED,
                    "max": MAX_SPEED,
                    "step": 0.05,
                    "default": 1.0,
                },
                "languages": [
                    {
                        "code": code,
                        "name": language["name"],
                        "available": language_available(code),
                        "voices": [
                            {"id": voice, "label": voice_label(voice)}
                            for voice in VOICES[code]
                        ],
                    }
                    for code, language in LANGUAGES.items()
                ],
                "max_blend_voices": MAX_BLEND_VOICES,
            },
        )

    # -- settings ------------------------------------------------------

    def validate(self, kind: str, settings: dict) -> dict:
        if not isinstance(settings, dict):
            raise SpeechError("The voice settings could not be read.")

        language = _language(settings.get("language"))
        speed = _speed(settings.get("speed", 1.0))

        if kind == ROLE_PRESET:
            voice = settings.get("voice")

            if voice not in VOICES[language]:
                raise SpeechError(
                    "That voice does not belong to that language."
                )

            return {"language": language, "voice": voice, "speed": speed}

        if kind == ROLE_BLEND:
            parts = settings.get("voices")

            if not isinstance(parts, list) or not (
                2 <= len(parts) <= MAX_BLEND_VOICES
            ):
                raise SpeechError(
                    f"A blend mixes 2 to {MAX_BLEND_VOICES} voices."
                )

            cleaned = []

            for part in parts:
                voice = part.get("voice") if isinstance(part, dict) else None

                if voice not in ALL_VOICES:
                    raise SpeechError(
                        "A blend can only use Kokoro's supplied voices."
                    )

                try:
                    weight = float(part.get("weight", 1.0))
                except (TypeError, ValueError):
                    raise SpeechError("Blend amounts must be numbers.")

                if not 0 < weight <= 100:
                    raise SpeechError(
                        "Each blend amount must be above zero."
                    )

                cleaned.append({"voice": voice, "weight": weight})

            if len({part["voice"] for part in cleaned}) != len(cleaned):
                raise SpeechError("A blend needs different voices.")

            return {"language": language, "voices": cleaned, "speed": speed}

        raise SpeechError("Kokoro cannot make that kind of voice.")

    # -- synthesis -----------------------------------------------------

    def _pipeline(self, language: str):
        if language not in self._pipelines:
            if self._pipeline_factory is not None:
                self._pipelines[language] = self._pipeline_factory(language)
            else:
                from kokoro import KPipeline

                # Every language shares one copy of the model.
                pipeline = KPipeline(
                    lang_code=language,
                    repo_id=REPO_ID,
                    model=self._model if self._model is not None else True,
                )
                self._model = pipeline.model
                self._pipelines[language] = pipeline

        return self._pipelines[language]

    def voice_for(self, kind: str, settings: dict):
        """
        What to hand a Kokoro pipeline as its voice: a supplied voice's
        name, or for a blend the weighted average of the voices' data.
        """
        if kind == ROLE_PRESET:
            return settings["voice"]

        import torch

        pipeline = self._pipeline(settings["language"])
        total = sum(part["weight"] for part in settings["voices"])

        return torch.stack(
            [
                pipeline.load_single_voice(part["voice"])
                * (part["weight"] / total)
                for part in settings["voices"]
            ]
        ).sum(dim=0)

    def synthesize(self, text: str, kind: str, settings: dict):
        settings = self.validate(kind, settings)

        with self._lock:
            pipeline = self._pipeline(settings["language"])
            voice = self.voice_for(kind, settings)

            parts: List[np.ndarray] = [
                np.asarray(audio, dtype=np.float32)
                for _, _, audio in pipeline(
                    text,
                    voice=voice,
                    speed=settings["speed"],
                )
                if audio is not None
            ]

        if not parts:
            raise SpeechError("Kokoro produced no audio for that text.")

        return np.concatenate(parts), SAMPLE_RATE

    def unload(self) -> None:
        with self._lock:
            self._pipelines.clear()
            self._model = None
