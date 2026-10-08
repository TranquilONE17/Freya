from freya.speech.engines import planned_engines
from freya.speech.kokoro_engine import KokoroEngine
from freya.speech.studio import VoiceStudio


def build_voice_studio(voice, profiles=None, clips=None) -> VoiceStudio:
    """
    Assemble the voice studio around Freya's live voice.

    Kokoro is the one engine that is ready out of the box. The others
    are listed as not set up, so the Voice tab can say what each kind
    of voice work would need.
    """
    pipeline = getattr(voice, "pipeline", None)

    kokoro = KokoroEngine(
        shared_model=getattr(pipeline, "model", None),
    )

    def apply_live_voice(profile):
        if profile is None:
            voice.reset_voice()
            return

        settings = profile["settings"]

        voice.set_voice(
            kokoro.voice_for(profile["kind"], settings),
            settings["speed"],
            settings["language"],
        )

    return VoiceStudio(
        [kokoro] + planned_engines(),
        profiles=profiles,
        clips=clips,
        apply_live_voice=apply_live_voice,
    )
