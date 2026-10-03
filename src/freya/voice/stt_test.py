from stt import FreyaSTT


def main():
    stt = FreyaSTT()

    audio_file = input(
        "Audio file: "
    ).strip().strip('"')

    transcript, info = stt.transcribe(
        audio_file
    )

    print()
    print(
        f"Detected language: "
        f"{info.language}"
    )
    print()
    print("Transcript:")
    print(transcript)


if __name__ == "__main__":
    main()