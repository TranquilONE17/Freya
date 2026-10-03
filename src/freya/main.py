from core.assistant import FreyaAssistant
from voice.tts import FreyaVoice


def main():
    freya = FreyaAssistant()
    voice = FreyaVoice()

    print("Freya online.")
    print("Voice: enabled")
    print("Type 'exit' to quit.\n")

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in {"exit", "quit"}:
            print("Freya: Goodbye.")
            voice.speak("Goodbye.")
            break

        if not user_input:
            continue

        reply = freya.respond(user_input)

        print(f"\nFreya: {reply}\n")

        voice.speak(reply)


if __name__ == "__main__":
    main()
