import re
import tempfile
from pathlib import Path

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

    def _split_into_chunks(self, text):
        text = text.strip()

        if not text:
            return []

        chunks = re.split(
            r"(?<=[.!?])\s+",
            text,
        )

        return [
            chunk.strip()
            for chunk in chunks
            if chunk.strip()
        ]

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

    def _play_audio(self, audio):
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

    def speak(self, text):
        if not self.enabled:
            return

        chunks = self._split_into_chunks(
            text
        )

        for chunk in chunks:
            audio = self._generate_audio(
                chunk
            )

            self._play_audio(
                audio
            )
