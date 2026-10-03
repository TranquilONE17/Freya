import re

from core.assistant import FreyaAssistant
from voice.stt import FreyaSTT
from voice.tts import FreyaVoice


VOICE_FILE_COMMAND = "/voice-file"
TALK_COMMAND = "/talk"


def extract_complete_sentences(buffer):
    sentences = []
    sentence_end = re.compile(
        r"(.+?[.!?]+)(?:\s+|$)",
        re.DOTALL,
    )

    while True:
        match = sentence_end.match(buffer)

        if match is None:
            break

        sentence = match.group(1).strip()

        if sentence:
            sentences.append(sentence)

        buffer = buffer[
            match.end():
        ]

    return sentences, buffer


def stream_freya_response(
    freya,
    voice,
    user_input,
):
    print(
        "\nFreya: ",
        end="",
        flush=True,
    )

    speech_buffer = ""

    for chunk in freya.respond_stream(
        user_input
    ):
        print(
            chunk,
            end="",
            flush=True,
        )

        speech_buffer += chunk

        sentences, speech_buffer = (
            extract_complete_sentences(
                speech_buffer
            )
        )

        for sentence in sentences:
            voice.speak(
                sentence
            )

    remaining_text = (
        speech_buffer.strip()
    )

    if remaining_text:
        voice.speak(
            remaining_text
        )

    print("\n")


def get_voice_file_path(command):
    path = command[
        len(VOICE_FILE_COMMAND):
    ].strip()

    return path.strip('"')


def main():
    freya = FreyaAssistant()
    voice = FreyaVoice()
    stt = None

    print("Freya online.")
    print("Voice: enabled")
    print("Streaming: enabled")
    print("Async voice: enabled")
    print("Voice-file input: enabled")
    print("Push-to-talk: enabled")
    print()
    print("Use /talk for microphone input.")
    print(
        "Use /voice-file <path> "
        "to transcribe an audio file."
    )
    print("Type 'exit' to quit.\n")

    try:
        while True:
            user_input = input(
                "You: "
            ).strip()

            if user_input.lower() in {
                "exit",
                "quit",
            }:
                print("Freya: Goodbye.")
                voice.speak("Goodbye.")
                voice.wait_until_done()
                break

            if not user_input:
                continue

            if user_input.lower() == TALK_COMMAND:
                try:
                    if stt is None:
                        stt = FreyaSTT()

                    audio_path = stt.record_push_to_talk()

                    transcript, info = stt.transcribe(
                        audio_path
                    )

                except Exception as exc:
                    print(
                        "\nMicrophone error: "
                        f"{exc}\n"
                    )
                    continue

                transcript = transcript.strip()

                if not transcript:
                    print(
                        "\nNo speech was "
                        "detected from the microphone.\n"
                    )
                    continue

                print()
                print(
                    "You (voice): "
                    f"{transcript}"
                )
                print(
                    "Detected language: "
                    f"{info.language}"
                )

                stream_freya_response(
                    freya,
                    voice,
                    transcript,
                )

                continue

            if user_input.lower().startswith(
                VOICE_FILE_COMMAND
            ):
                audio_path = get_voice_file_path(
                    user_input
                )

                if not audio_path:
                    print(
                        "\nUsage: "
                        "/voice-file "
                        "<audio file path>\n"
                    )
                    continue

                try:
                    if stt is None:
                        stt = FreyaSTT()

                    transcript, info = (
                        stt.transcribe(
                            audio_path
                        )
                    )
                except Exception as exc:
                    print(
                        "\nVoice-file error: "
                        f"{exc}\n"
                    )
                    continue

                transcript = transcript.strip()

                if not transcript:
                    print(
                        "\nNo speech was "
                        "detected in that "
                        "audio file.\n"
                    )
                    continue

                print()
                print(
                    "You (voice): "
                    f"{transcript}"
                )
                print(
                    "Detected language: "
                    f"{info.language}"
                )

                stream_freya_response(
                    freya,
                    voice,
                    transcript,
                )

                continue

            stream_freya_response(
                freya,
                voice,
                user_input,
            )

    except KeyboardInterrupt:
        print(
            "\nFreya: Shutting down."
        )

    finally:
        voice.shutdown()


if __name__ == "__main__":
    main()
