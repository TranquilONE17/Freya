from pathlib import Path

import soundfile as sf
from kokoro import KPipeline


VOICES = [
    "af_heart",
    "af_bella",
    "af_nicole",
    "af_sarah",
    "af_sky",
]

TEXT = (
    "Hello Justin. I'm Freya. "
    "It's good to finally have a voice. "
    "I'm ready whenever you are."
)

OUTPUT_DIR = Path("voice_samples")


def generate_voice_sample(
    pipeline,
    voice_name,
):
    print(f"Generating {voice_name}...")

    generator = pipeline(
        TEXT,
        voice=voice_name,
        speed=1.0,
    )

    audio_parts = []

    for _, _, audio in generator:
        audio_parts.append(audio)

    if not audio_parts:
        print(
            f"No audio generated for "
            f"{voice_name}."
        )
        return

    import numpy as np

    audio = np.concatenate(
        audio_parts
    )

    output_file = (
        OUTPUT_DIR
        / f"{voice_name}.wav"
    )

    sf.write(
        output_file,
        audio,
        24000,
    )

    print(
        f"Saved: {output_file}"
    )


def main():
    OUTPUT_DIR.mkdir(
        exist_ok=True
    )

    print(
        "Loading Freya voice engine..."
    )

    pipeline = KPipeline(
        lang_code="a",
        repo_id="hexgrad/Kokoro-82M",
    )

    print()

    for voice_name in VOICES:
        generate_voice_sample(
            pipeline,
            voice_name,
        )

    print()
    print(
        "Voice audition complete."
    )
    print(
        f"Samples saved in: "
        f"{OUTPUT_DIR.resolve()}"
    )


if __name__ == "__main__":
    main()