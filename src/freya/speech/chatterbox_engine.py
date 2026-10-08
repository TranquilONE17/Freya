from freya.speech.engines import ROLE_CLONE, EngineInfo, SpeechError
from freya.speech.helper import HelperEngine, number
from freya.speech.references import ORIGIN_UPLOAD


ENGINE_ID = "chatterbox"

# The languages of Chatterbox Multilingual, as its own code lists them.
LANGUAGES = {
    "ar": "Arabic", "da": "Danish", "de": "German", "el": "Greek",
    "en": "English", "es": "Spanish", "fi": "Finnish", "fr": "French",
    "he": "Hebrew", "hi": "Hindi", "it": "Italian", "ja": "Japanese",
    "ko": "Korean", "ms": "Malay", "nl": "Dutch", "no": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "ru": "Russian", "sv": "Swedish",
    "sw": "Swahili", "tr": "Turkish", "zh": "Chinese",
}

TEMPERATURE = {"min": 0.3, "max": 1.2, "step": 0.05, "default": 0.8}
EXAGGERATION = {"min": 0.25, "max": 1.5, "step": 0.05, "default": 0.5}
CFG_WEIGHT = {"min": 0.0, "max": 1.0, "step": 0.05, "default": 0.5}

# Each model and the controls it really has. Turbo and Nano ignore
# exaggeration and pace, so those are not offered for them.
MODELS = {
    "turbo": {
        "name": "Turbo (English)",
        "languages": ("en",),
        "controls": ("temperature",),
    },
    "multilingual": {
        "name": "Multilingual V3 (23 languages)",
        "languages": tuple(LANGUAGES),
        "controls": ("temperature", "exaggeration", "cfg_weight"),
    },
    "nano": {
        "name": "Nano (English, smallest)",
        "languages": ("en",),
        "controls": ("temperature",),
    },
}


class ChatterboxEngine(HelperEngine):
    """
    Chatterbox: speaks in the voice of a reference recording.

    Chatterbox marks everything it generates with an inaudible
    watermark. Freya leaves that in place.
    """

    id = ENGINE_ID
    worker_script = "chatterbox_worker.py"
    gpu_megabytes_needed = 5000

    def info(self) -> EngineInfo:
        return EngineInfo(
            id=ENGINE_ID,
            name="Chatterbox",
            summary=(
                "Voice cloning from a reference recording, and "
                "expressive speech."
            ),
            roles=(ROLE_CLONE,),
            status=self._status(),
            detail=(
                "Runs on this computer. Its speech carries Chatterbox's "
                "built-in inaudible watermark."
                if self.installed
                else "Needs its own environment and model files."
            ),
            controls={
                "models": [
                    {
                        "id": model_id,
                        "name": model["name"],
                        "languages": [
                            {"code": code, "name": LANGUAGES[code]}
                            for code in model["languages"]
                        ],
                        "controls": list(model["controls"]),
                    }
                    for model_id, model in MODELS.items()
                ],
                "temperature": TEMPERATURE,
                "exaggeration": EXAGGERATION,
                "cfg_weight": CFG_WEIGHT,
                "reference": {"transcript": False},
            },
        )

    def validate(self, kind: str, settings: dict) -> dict:
        if kind != ROLE_CLONE:
            raise SpeechError("Chatterbox cannot make that kind of voice.")

        if not isinstance(settings, dict):
            raise SpeechError("The voice settings could not be read.")

        model_id = settings.get("model", "turbo")

        if model_id not in MODELS:
            raise SpeechError("That Chatterbox model is not known.")

        model = MODELS[model_id]
        language = settings.get("language", model["languages"][0])

        if language not in model["languages"]:
            raise SpeechError("That model does not speak that language.")

        reference = self._references.get(settings.get("reference"))

        if reference is None or reference["origin"] != ORIGIN_UPLOAD:
            raise SpeechError("Choose a reference recording first.")

        if reference.get("consent") is not True:
            raise SpeechError(
                "Confirm that you have the right to use this voice "
                "before cloning it."
            )

        cleaned = {
            "model": model_id,
            "language": language,
            "reference": reference["id"],
            "temperature": number(
                settings.get("temperature"),
                TEMPERATURE["min"],
                TEMPERATURE["max"],
                TEMPERATURE["default"],
                "Variation",
            ),
        }

        if "exaggeration" in model["controls"]:
            cleaned["exaggeration"] = number(
                settings.get("exaggeration"),
                EXAGGERATION["min"],
                EXAGGERATION["max"],
                EXAGGERATION["default"],
                "Expressiveness",
            )
            cleaned["cfg_weight"] = number(
                settings.get("cfg_weight"),
                CFG_WEIGHT["min"],
                CFG_WEIGHT["max"],
                CFG_WEIGHT["default"],
                "Pace",
            )

        return cleaned

    def synthesize(self, text: str, kind: str, settings: dict):
        settings = self.validate(kind, settings)

        return self._run(
            "synthesize",
            text=text,
            settings=settings,
            reference=str(self._references.path(settings["reference"])),
        )

    def watermark_strength(self, path) -> float:
        """
        How strongly Chatterbox's watermark is detected in a WAV file
        (1.0 is fully present). Used to check Freya keeps it intact.
        """
        return float(
            self._helper.request({"op": "watermark", "path": str(path)})[
                "watermark"
            ]
        )

    def speaker_similarity(self, reference_path, path) -> float:
        """
        How alike the speakers of two WAV files sound, from -1 to 1,
        by Chatterbox's speaker encoder. Used by the benchmark.
        """
        return float(
            self._helper.request(
                {
                    "op": "similarity",
                    "reference": str(reference_path),
                    "path": str(path),
                }
            )["similarity"]
        )
