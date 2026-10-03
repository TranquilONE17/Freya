import queue
import re
import tempfile
import threading
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

        self._speech_queue = queue.Queue()
        self._shutdown_event = threading.Event()
        self._worker = None

        if self.enabled:
            print("Loading Freya voice engine...")
            self.pipeline = KPipeline(
                lang_code="a",
                repo_id="hexgrad/Kokoro-82M",
            )

            self._worker = threading.Thread(
                target=self._speech_worker,
                name="FreyaVoiceWorker",
                daemon=True,
            )
            self._worker.start()

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
                f"\n[Voice playback error: {exc}]"
            )

    def _speech_worker(self):
        while True:
            item = self._speech_queue.get()

            try:
                if item is None:
                    return

                audio = self._generate_audio(
                    item
                )

                self._play_audio(
                    audio
                )
            except Exception as exc:
                print(
                    f"\n[Voice worker error: {exc}]"
                )
            finally:
                self._speech_queue.task_done()

    def speak(self, text):
        if (
            not self.enabled
            or self._shutdown_event.is_set()
        ):
            return

        chunks = self._split_into_chunks(
            text
        )

        for chunk in chunks:
            self._speech_queue.put(
                chunk
            )

    def wait_until_done(self):
        if not self.enabled:
            return

        self._speech_queue.join()

    def shutdown(self):
        if (
            not self.enabled
            or self._shutdown_event.is_set()
        ):
            return

        self._shutdown_event.set()

        self._speech_queue.put(
            None
        )

        if self._worker is not None:
            self._worker.join()
