import re

from core.assistant import FreyaAssistant
from voice.tts import FreyaVoice


def extract_complete_sentences(buffer):
    sentences = []
    sentence_end = re.compile(
        r"(.+?[.!?]+)(?:\\s+|$)",
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


def main():
    freya = FreyaAssistant()
    voice = FreyaVoice()

    print("Freya online.")
    print("Voice: enabled")
    print("Streaming: enabled")
    print("Async voice: enabled")
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

    except KeyboardInterrupt:
        print(
            "\nFreya: Shutting down."
        )

    finally:
        voice.shutdown()


if __name__ == "__main__":
    main()
