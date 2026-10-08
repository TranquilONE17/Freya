from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# What a speech engine can do. The Voice tab offers each kind of work
# only through engines that declare it.
ROLE_PRESET = "preset"      # speak with voices the engine ships with
ROLE_BLEND = "blend"        # mix the engine's own supplied voices
ROLE_CLONE = "clone"        # imitate a voice from a reference recording
ROLE_DESIGN = "design"      # create a new voice from a description

ROLES = (ROLE_PRESET, ROLE_BLEND, ROLE_CLONE, ROLE_DESIGN)

STATUS_READY = "ready"
STATUS_NOT_INSTALLED = "not_installed"
STATUS_NOT_CONFIGURED = "not_configured"


class SpeechError(Exception):
    """
    A speech request could not be carried out. The message is written
    for the owner and is safe to show in the window.
    """


@dataclass
class EngineInfo:
    """
    What the window needs to know about one speech engine.
    """

    id: str
    name: str
    summary: str
    roles: Tuple[str, ...]
    status: str
    detail: str = ""
    # False for an engine that sends text or audio off this computer.
    local: bool = True
    # The controls this engine really supports; the window shows no others.
    controls: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "roles": list(self.roles),
            "status": self.status,
            "detail": self.detail,
            "local": self.local,
            "controls": self.controls,
        }


class SpeechEngine:
    """
    Base class for a speech engine.

    A profile's settings are private to the engine that made them: a
    preset name, a blend recipe, a cloning reference, and a cloud voice
    ID are not interchangeable, so an engine is only ever handed
    settings from its own profiles.
    """

    id = ""

    def info(self) -> EngineInfo:
        raise NotImplementedError

    def validate(self, kind: str, settings: dict) -> dict:
        """
        Check settings for a profile of the given kind and return the
        cleaned form to store. Raises SpeechError when they are not
        acceptable.
        """
        raise NotImplementedError

    def synthesize(self, text: str, kind: str, settings: dict):
        """
        Return (audio, sample_rate): mono float32 samples.
        """
        raise NotImplementedError

    def unload(self) -> None:
        """
        Release the engine's models. Called to free memory.
        """


class PlannedEngine(SpeechEngine):
    """
    An engine Freya knows about but that is not set up on this computer.

    It is listed so the window can say what each kind of voice work
    would need, without pretending the engine is usable.
    """

    def __init__(self, info: EngineInfo):
        self.id = info.id
        self._info = info

    def info(self) -> EngineInfo:
        return self._info

    def validate(self, kind: str, settings: dict) -> dict:
        raise SpeechError(f"{self._info.name} is not set up yet.")

    def synthesize(self, text: str, kind: str, settings: dict):
        raise SpeechError(f"{self._info.name} is not set up yet.")


def planned_engines() -> List[SpeechEngine]:
    """
    The engines that need their own install before they can be used.
    """
    return [
        PlannedEngine(
            EngineInfo(
                id="chatterbox",
                name="Chatterbox",
                summary=(
                    "Voice cloning from a reference recording, and "
                    "expressive speech."
                ),
                roles=(ROLE_CLONE,),
                status=STATUS_NOT_INSTALLED,
                detail=(
                    "Needs its own environment (it requires different "
                    "library versions from Freya) and its model files."
                ),
            )
        ),
        PlannedEngine(
            EngineInfo(
                id="qwen3-tts",
                name="Qwen3-TTS",
                summary=(
                    "Designs an original voice from a description, "
                    "and clones a voice from a reference recording."
                ),
                roles=(ROLE_DESIGN, ROLE_CLONE),
                status=STATUS_NOT_INSTALLED,
                detail=(
                    "Needs its own environment (it requires different "
                    "library versions from Freya) and its model files."
                ),
            )
        ),
        PlannedEngine(
            EngineInfo(
                id="elevenlabs",
                name="ElevenLabs",
                summary=(
                    "Cloud voice cloning, voice design, and speech. "
                    "Text and recordings are sent to ElevenLabs."
                ),
                roles=(ROLE_CLONE, ROLE_DESIGN),
                status=STATUS_NOT_CONFIGURED,
                detail=(
                    "Optional cloud service. Needs an ElevenLabs "
                    "account and API key; nothing is sent unless it "
                    "is set up."
                ),
                local=False,
            )
        ),
    ]


def find_engine(engines: List[SpeechEngine], engine_id: str) -> Optional[SpeechEngine]:
    for engine in engines:
        if engine.id == engine_id:
            return engine

    return None
