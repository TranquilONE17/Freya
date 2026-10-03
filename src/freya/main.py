import ollama


MODEL = "gpt-oss:20b"


def main():
    print("Freya online.")
    print("Type 'exit' to quit.\n")

    messages = [
        {
            "role": "system",
            "content": (
                "You are Freya, a locally hosted personal AI assistant. "
                "Your name is Freya. "
                "Be helpful, conversational, capable, and concise."
            ),
        }
    ]

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in {"exit", "quit"}:
            print("Freya: Goodbye.")
            break

        if not user_input:
            continue

        messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        response = ollama.chat(
            model=MODEL,
            messages=messages,
        )

        reply = response["message"]["content"]

        messages.append(
            {
                "role": "assistant",
                "content": reply,
            }
        )

        print(f"\nFreya: {reply}\n")


if __name__ == "__main__":
    main()