from pathlib import Path

from faster_whisper import WhisperModel


WHISPER_MODEL = "small"
WHISPER_DEVICE = "cuda"
WHISPER_COMPUTE_TYPE = "float16"


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