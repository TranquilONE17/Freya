from core.assistant import FreyaAssistant


def main():
    freya = FreyaAssistant()

    print("Freya online.")
    print("Type 'exit' to quit.\n")

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in {"exit", "quit"}:
            print("Freya: Goodbye.")
            break

        if not user_input:
            continue

        reply = freya.respond(user_input)

        print(f"\nFreya: {reply}\n")


if __name__ == "__main__":
    main()