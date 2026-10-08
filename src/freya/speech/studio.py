from typing import Callable, List, Optional

from freya.speech.engines import (
    ROLE_BLEND,
    ROLE_CLONE,
    ROLE_DESIGN,
    ROLE_PRESET,
    STATUS_READY,
    SpeechEngine,
    SpeechError,
    find_engine,
)
from freya.speech.references import (
    MAX_SECONDS,
    MIN_SECONDS,
    ReferenceStore,
)
from freya.speech.store import ClipStore, VoiceProfileStore


MAX_TEXT_LENGTH = 600

DEFAULT_SAMPLE_TEXT = (
    "Hello. This is how I sound with this voice."
)

# The sections of the Voice tab, and the kind of work each one needs.
# The playground speaks with any engine that is ready.
SECTIONS = {
    "clone": ROLE_CLONE,
    "design": ROLE_DESIGN,
    "preset": ROLE_PRESET,
    "blend": ROLE_BLEND,
}

# Freya's own speaking voice runs on this engine, so only its profiles
# can become her voice.
LIVE_ENGINE = "kokoro"
LIVE_LANGUAGES = ("a", "b")


class VoiceStudio:
    """
    Everything behind the Voice tab: which engines can do what, trying
    voices out, and the owner's saved voices.
    """

    def __init__(
        self,
        engines: List[SpeechEngine],
        profiles: Optional[VoiceProfileStore] = None,
        clips: Optional[ClipStore] = None,
        apply_live_voice: Optional[Callable[[Optional[dict]], None]] = None,
        references: Optional[ReferenceStore] = None,
    ):
        self._engines = engines
        self.profiles = profiles or VoiceProfileStore()
        self.clips = clips or ClipStore()
        self.references = references or ReferenceStore()
        self._apply_live_voice = apply_live_voice

    # -- what the window shows -------------------------------------------

    def describe(self) -> dict:
        infos = [engine.info() for engine in self._engines]
        loaded = {
            engine.id: bool(getattr(engine, "loaded", False))
            for engine in self._engines
        }

        sections = {
            section: [info.id for info in infos if role in info.roles]
            for section, role in SECTIONS.items()
        }
        sections["playground"] = [
            info.id for info in infos if info.status == STATUS_READY
        ]

        return {
            "engines": [
                {**info.as_dict(), "loaded": loaded[info.id]}
                for info in infos
            ],
            "sections": sections,
            "profiles": [
                {
                    **profile,
                    "can_be_freyas_voice": self._can_be_live(profile),
                }
                for profile in self.profiles.list()
            ],
            "active_profile": self.profiles.active_id,
            "sample_text": DEFAULT_SAMPLE_TEXT,
            "max_text_length": MAX_TEXT_LENGTH,
            "reference_seconds": {"min": MIN_SECONDS, "max": MAX_SECONDS},
        }

    @staticmethod
    def _can_be_live(profile: dict) -> bool:
        return (
            profile["engine"] == LIVE_ENGINE
            and profile["settings"].get("language") in LIVE_LANGUAGES
        )

    # -- engines ---------------------------------------------------------

    def _ready_engine(self, engine_id) -> SpeechEngine:
        engine = find_engine(self._engines, engine_id)

        if engine is None:
            raise SpeechError("That speech engine is not known.")

        info = engine.info()

        if info.status != STATUS_READY:
            raise SpeechError(f"{info.name} is not set up yet.")

        self._make_way_for(engine)

        return engine

    def _make_way_for(self, engine: SpeechEngine) -> None:
        """
        The large engines do not fit in memory together, so the
        others are unloaded before one of them is used.
        """
        if not getattr(engine, "exclusive", False):
            return

        for other in self._engines:
            if other is not engine and getattr(other, "exclusive", False):
                other.unload()

    @staticmethod
    def _text(text) -> str:
        text = " ".join(str(text or "").split())

        if not text:
            raise SpeechError("There is nothing to say.")

        if len(text) > MAX_TEXT_LENGTH:
            raise SpeechError(
                f"The text can be at most {MAX_TEXT_LENGTH} characters."
            )

        return text

    # -- actions -----------------------------------------------------------

    def preview(self, engine_id, kind, settings, text=None) -> dict:
        """
        Speak some text with settings that have not been saved, and
        return the clip.
        """
        engine = self._ready_engine(engine_id)

        if kind not in engine.info().roles:
            raise SpeechError(
                f"{engine.info().name} cannot make that kind of voice."
            )

        text = self._text(text or DEFAULT_SAMPLE_TEXT)
        cleaned = engine.validate(kind, settings)
        audio, sample_rate = engine.synthesize(text, kind, cleaned)

        return self.clips.add(audio, sample_rate, engine.id, text)

    def speak(self, profile_id, text) -> dict:
        """
        Speak some text with a saved voice, using the engine that the
        voice belongs to.
        """
        profile = self.profiles.get(profile_id)

        if profile is None:
            raise SpeechError("That saved voice no longer exists.")

        engine = self._ready_engine(profile["engine"])
        text = self._text(text)
        audio, sample_rate = engine.synthesize(
            text,
            profile["kind"],
            profile["settings"],
        )

        return self.clips.add(audio, sample_rate, engine.id, text)

    def save_profile(self, name, engine_id, kind, settings) -> dict:
        engine = self._ready_engine(engine_id)

        if kind not in engine.info().roles:
            raise SpeechError(
                f"{engine.info().name} cannot make that kind of voice."
            )

        return self.profiles.add(
            name,
            engine.id,
            kind,
            engine.validate(kind, settings),
        )

    def delete_profile(self, profile_id) -> None:
        was_active = self.profiles.active_id == profile_id
        profile = self.profiles.get(profile_id)

        if not self.profiles.delete(profile_id):
            raise SpeechError("That saved voice no longer exists.")

        # The recording the voice was made from goes with it, unless
        # another saved voice still uses it.
        reference = profile["settings"].get("reference")

        if reference and not any(
            other["settings"].get("reference") == reference
            for other in self.profiles.list()
        ):
            self.references.delete(reference)

        if was_active and self._apply_live_voice is not None:
            self._apply_live_voice(None)

    def use_profile(self, profile_id) -> None:
        """
        Make a saved voice Freya's own speaking voice, or pass None to
        return to her default.
        """
        profile = None

        if profile_id is not None:
            profile = self.profiles.get(profile_id)

            if profile is None:
                raise SpeechError("That saved voice no longer exists.")

            if not self._can_be_live(profile):
                raise SpeechError(
                    "Freya speaks English with Kokoro, so only an "
                    "English Kokoro voice can be her voice."
                )

        if self._apply_live_voice is not None:
            self._apply_live_voice(profile)

        self.profiles.set_active(profile_id)

    def restore_live_voice(self) -> None:
        """
        At start-up, put back the voice the owner chose last time.
        """
        profile = self.profiles.get(self.profiles.active_id)

        if (
            profile is not None
            and self._can_be_live(profile)
            and self._apply_live_voice is not None
        ):
            self._apply_live_voice(profile)

    def unload(self) -> None:
        for engine in self._engines:
            engine.unload()

    def free_memory(self) -> None:
        """
        Unload the large engines. Kokoro stays, because Freya's own
        voice uses it.
        """
        for engine in self._engines:
            if getattr(engine, "exclusive", False):
                engine.unload()

    # -- recordings ------------------------------------------------------

    @staticmethod
    def _public_reference(reference: dict) -> dict:
        return {
            "id": reference["id"],
            "origin": reference["origin"],
            "seconds": reference["seconds"],
        }

    def add_reference(self, pcm, sample_rate, consent, transcript="") -> dict:
        """
        Take a recording to clone a voice from. Refused unless the
        owner states they have the right to use that voice.
        """
        return self._public_reference(
            self.references.add_upload(pcm, sample_rate, consent, transcript)
        )

    def design(self, engine_id, settings, text=None):
        """
        Have an engine invent a voice from a description. Returns the
        sample as a clip, and the recording a voice can be saved from.
        """
        engine = self._ready_engine(engine_id)

        if ROLE_DESIGN not in engine.info().roles:
            raise SpeechError(
                f"{engine.info().name} cannot design a voice from a "
                "description."
            )

        text = self._text(text or DEFAULT_SAMPLE_TEXT)
        audio, sample_rate = engine.design(text, settings)
        reference = self.references.add_designed(
            audio, sample_rate, engine.id, text
        )

        return (
            self.clips.add(audio, sample_rate, engine.id, text),
            self._public_reference(reference),
        )

    def forget_unsaved_recordings(self) -> None:
        """
        Delete every recording that no saved voice uses.
        """
        self.references.keep_only(
            profile["settings"].get("reference")
            for profile in self.profiles.list()
        )

    # -- requests from the window ----------------------------------------

    def handle(self, message: dict) -> dict:
        """
        Carry out one request from the Voice tab.

        Always returns the studio's state afterwards, with the clip
        that was generated (if any) and an error message (if it
        failed). Nothing in the message is trusted: every field is
        checked by the method it is passed to.
        """
        clip = None
        reference = None
        error = None

        try:
            action = message.get("action")

            if action == "preview":
                clip = self.preview(
                    message.get("engine"),
                    message.get("kind"),
                    message.get("settings"),
                    message.get("text"),
                )
            elif action == "speak":
                clip = self.speak(
                    message.get("profile"),
                    message.get("text"),
                )
            elif action == "save":
                self.save_profile(
                    message.get("name"),
                    message.get("engine"),
                    message.get("kind"),
                    message.get("settings"),
                )
            elif action == "delete":
                self.delete_profile(message.get("profile"))
            elif action == "use":
                self.use_profile(message.get("profile"))
            elif action == "reference":
                reference = self.add_reference(
                    message.get("upload"),
                    message.get("sample_rate"),
                    message.get("consent"),
                    message.get("transcript"),
                )
            elif action == "design":
                clip, reference = self.design(
                    message.get("engine"),
                    message.get("settings"),
                    message.get("text"),
                )
            elif action == "free":
                self.free_memory()
            elif action != "state":
                raise SpeechError("The Voice tab asked for something unknown.")
        except SpeechError as exc:
            error = str(exc)
        except Exception as exc:
            error = f"That did not work: {exc}"

        return {
            "state": self.describe(),
            "clip": clip,
            "reference": reference,
            "error": error,
        }
