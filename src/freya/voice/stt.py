from pathlib import Path
import tempfile

import numpy as np
import sounddevice as sd
import soundfile as sf
from faster_whisper import WhisperModel


WHISPER_MODEL = "small"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE_TYPE = "float16"

MICROPHONE_DEVICE = 1
MICROPHONE_SAMPLE_RATE = 44100
MICROPHONE_CHANNELS = 1


class FreyaSTT:
    def __init__(self):
        print("Loading Freya speech recognition engine...")

        self.model = WhisperModel(
            WHISPER_MODEL,
            device=WHISPER_DEVICE,
            compute_type=WHISPER_COMPUTE_TYPE,
        )

        print("Freya speech recognition ready.")

    def transcribe(self, audio_file):
        audio_path = Path(audio_file)

        if not audio_path.exists():
            raise FileNotFoundError(
                f"Audio file not found: {audio_path}"
            )

        print(f"Transcribing: {audio_path.name}")

        segments, info = self.model.transcribe(
            str(audio_path),
            beam_size=5,
            vad_filter=True,
        )

        text_parts = []

        for segment in segments:
            text = segment.text.strip()

            if text:
                text_parts.append(text)

        transcript = " ".join(text_parts)

        return transcript, info

    def record_push_to_talk(self):
        print()
        input("Press ENTER to start talking...")

        print("Listening... Press ENTER again to stop.")

        frames = []

        def callback(indata, frames_count, time_info, status):
            if status:
                print(f"Microphone status: {status}")
            frames.append(indata.copy())

        with sd.InputStream(
            device=MICROPHONE_DEVICE,
            samplerate=MICROPHONE_SAMPLE_RATE,
            channels=MICROPHONE_CHANNELS,
            dtype="float32",
            callback=callback,
        ):
            input()

        if not frames:
            raise RuntimeError("No microphone audio was captured.")

        audio = np.concatenate(frames, axis=0)
        temp_path = Path(tempfile.gettempdir()) / "freya_microphone.wav"

        sf.write(
            temp_path,
            audio,
            MICROPHONE_SAMPLE_RATE,
        )

        print("Recording stopped.")
        return temp_path

