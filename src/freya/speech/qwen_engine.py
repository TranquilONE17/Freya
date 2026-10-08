from freya.speech.engines import (
    ROLE_CLONE,
    ROLE_DESIGN,
    EngineInfo,
    SpeechError,
)
from freya.speech.helper import HelperEngine
from freya.speech.references import ORIGIN_DESIGNED, ORIGIN_UPLOAD


ENGINE_ID = "qwen3-tts"

# The languages Qwen3-TTS reports supporting.
LANGUAGES = (
    "English", "Chinese", "Japanese", "Korean", "German", "French",
    "Russian", "Portuguese", "Spanish", "Italian",
)

MODELS = {
    "1.7b": "1.7B (best quality)",
    "0.6b": "0.6B (smaller and faster)",
}

MAX_DESCRIPTION_LENGTH = 400


def _language(settings: dict) -> str:
    language = settings.get("language", "English")

    if language not in LANGUAGES:
        raise SpeechError("That language is not one Qwen3-TTS supports.")

    return language


def _model(settings: dict) -> str:
    model = settings.get("model", "1.7b")

    if model not in MODELS:
        raise SpeechError("That Qwen3-TTS model is not known.")

    return model


class QwenEngine(HelperEngine):
    """
    Qwen3-TTS: designs a new voice from a written description, and
    speaks in the voice of a reference recording.

    A designed voice is kept as the short sample the design model
    generated; speech is then made from that sample, so the voice
    stays the same from one sentence to the next.
    """

    id = ENGINE_ID
    worker_script = "qwen_worker.py"
    gpu_megabytes_needed = 7000

    def info(self) -> EngineInfo:
        return EngineInfo(
            id=ENGINE_ID,
            name="Qwen3-TTS",
            summary=(
                "Designs an original voice from a description, and "
                "clones a voice from a reference recording."
            ),
            roles=(ROLE_DESIGN, ROLE_CLONE),
            status=self._status(),
            detail=(
                "Runs on this computer."
                if self.installed
                else "Needs its own environment and model files."
            ),
            controls={
                "models": [
                    {
                        "id": model_id,
                        "name": name,
                        "languages": [
                            {"code": language, "name": language}
                            for language in LANGUAGES
                        ],
                        "controls": [],
                    }
                    for model_id, name in MODELS.items()
                ],
                "languages": [
                    {"code": language, "name": language}
                    for language in LANGUAGES
                ],
                "max_description_length": MAX_DESCRIPTION_LENGTH,
                # A transcript of the recording improves the clone.
                "reference": {"transcript": True},
            },
        )

    # -- designing a voice ---------------------------------------------

    def validate_design(self, settings: dict) -> dict:
        if not isinstance(settings, dict):
            raise SpeechError("The voice settings could not be read.")

        description = " ".join(str(settings.get("description") or "").split())

        if not description:
            raise SpeechError("Describe the voice you want.")

        if len(description) > MAX_DESCRIPTION_LENGTH:
            raise SpeechError(
                "The description can be at most "
                f"{MAX_DESCRIPTION_LENGTH} characters."
            )

        return {"description": description, "language": _language(settings)}

    def design(self, text: str, settings: dict):
        """
        Generate a sample of a new voice matching a description.
        Returns (audio, sample_rate).
        """
        return self._run(
            "design",
            text=text,
            settings=self.validate_design(settings),
        )

    # -- speaking --------------------------------------------------------

    def validate(self, kind: str, settings: dict) -> dict:
        if kind not in (ROLE_CLONE, ROLE_DESIGN):
            raise SpeechError("Qwen3-TTS cannot make that kind of voice.")

        if not isinstance(settings, dict):
            raise SpeechError("The voice settings could not be read.")

        reference = self._references.get(settings.get("reference"))
        cleaned = {"language": _language(settings), "model": _model(settings)}

        if kind == ROLE_CLONE:
            if reference is None or reference["origin"] != ORIGIN_UPLOAD:
                raise SpeechError("Choose a reference recording first.")

            if reference.get("consent") is not True:
                raise SpeechError(
                    "Confirm that you have the right to use this voice "
                    "before cloning it."
                )
        else:
            # A designed voice is only ever spoken from a sample this
            # engine generated itself.
            if (
                reference is None
                or reference["origin"] != ORIGIN_DESIGNED
                or reference.get("engine") != ENGINE_ID
            ):
                raise SpeechError("Generate the designed voice first.")

            cleaned["description"] = self.validate_design(settings)[
                "description"
            ]

        cleaned["reference"] = reference["id"]

        return cleaned

    def synthesize(self, text: str, kind: str, settings: dict):
        settings = self.validate(kind, settings)
        reference = self._references.get(settings["reference"])

        return self._run(
            "synthesize",
            text=text,
            settings=settings,
            reference=str(self._references.path(reference["id"])),
            reference_text=reference.get("text") or "",
        )
