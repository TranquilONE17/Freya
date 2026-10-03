from config import SYSTEM_PROMPT
from core.llm import chat


class FreyaAssistant:
    def __init__(self):
        self.messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ]

    def respond(self, user_input):
        self.messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        reply = chat(self.messages)

        self.messages.append(
            {
                "role": "assistant",
                "content": reply,
            }
        )

        return reply