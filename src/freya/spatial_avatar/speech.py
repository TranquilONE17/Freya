"""
How speech reaches the avatar, and where lip synchronisation will plug
in.

The avatar is told about speech in four phases (started, progress,
completed, interrupted) by whatever is speaking. It does not know or
care which text-to-speech engine that is: the voice reports the phases
through SpeechListener and the avatar turns them into the SPEECH
command. Phase 1 uses only "is she speaking"; the rest of this file is
interface, not implementation.
"""
from dataclasses import dataclass
from typing import List, Optional, Protocol


class SpeechListener(Protocol):
    """
    Told what the voice is doing. Implemented by anything that wants
    to react to speech; called from the voice's own thread, so an
    implementation must return quickly and must not raise.
    """

    def speech_started(self, text: str) -> None: ...

    def speech_progress(self, level: float) -> None:
        """
        `level` is loudness from 0 to 1 at this moment, for engines
        that can report it. Optional: Phase 1 sends none.
        """

    def speech_completed(self) -> None: ...

    def speech_interrupted(self) -> None: ...


# -- future: lip synchronisation and facial animation -------------------


@dataclass(frozen=True)
class Viseme:
    """
    One mouth shape at one moment. NOT IMPLEMENTED: defined so that
    engines which can supply timing have something to supply.
    """

    time: float        # seconds from the start of the utterance
    shape: str         # for example "aa", "oh", "mm", "rest"
    weight: float = 1.0


@dataclass(frozen=True)
class FaceFrame:
    """
    A face pose at one moment, as named weights from 0 to 1 (for
    example ARKit-style blend shapes). NOT IMPLEMENTED.
    """

    time: float
    weights: dict


class FacialAnimationBackend(Protocol):
    """
    Turns speech into facial animation. NOT IMPLEMENTED in Phase 1.

    A backend may work from phoneme timing a speech engine provides
    (visemes), or from the audio itself (as NVIDIA Audio2Face does). It
    is chosen independently of the renderer and of the speech engine,
    and none is required: without one, the avatar opens and closes her
    mouth while speaking.

    A backend that loads a model declares what it needs so that it is
    started only when the resources are there, and can be unloaded.
    """

    id: str
    needs_gpu: bool

    def available(self) -> bool: ...

    def visemes(self, text: str, audio, sample_rate: int) -> Optional[List[Viseme]]: ...

    def face_frames(self, audio, sample_rate: int) -> Optional[List[FaceFrame]]: ...

    def unload(self) -> None: ...
