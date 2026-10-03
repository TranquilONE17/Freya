from pathlib import Path
import tempfile

import numpy as np
import soundfile as sf
from kokoro import KPipeline


VOICE_ENABLED = True
FREYA_VOICE = "af_heart"
VOICE_SPEED = 1.0
SAMPLE_RATE = 24000


class FreyaVoice:
    def __init__(self):
        self.enabled = VOICE_ENABLED
        self.voice = FREYA_VOICE
        self.speed = VOICE_SPEED
        self.pipeline = None

        if self.enabled:
            print("Loading Freya voice engine...")
            self.pipeline = KPipeline(
                lang_code="a",
                repo_id="hexgrad/Kokoro-82M",
            )

    def _generate_audio(self, text):
        if not self.enabled or not text.strip():
            return None

        generator = self.pipeline(
            text,
            voice=self.voice,
            speed=self.speed,
        )

        audio_parts = []

        for _, _, audio in generator:
            audio_parts.append(audio)

        if not audio_parts:
            return None

        return np.concatenate(audio_parts)

    def speak(self, text):
        audio = self._generate_audio(text)

        if audio is None:
            return

        temp_path = (
            Path(tempfile.gettempdir())
            / "freya_tts.wav"
        )

        sf.write(
            temp_path,
            audio,
            SAMPLE_RATE,
        )

        try:
            import winsound

            winsound.PlaySound(
                str(temp_path),
                winsound.SND_FILENAME,
            )
        except Exception as exc:
            print(
                f"[Voice playback error: {exc}]"
            )
