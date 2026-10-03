from config import SYSTEM_PROMPT
from core.llm import chat
from memory.memory_manager import MemoryManager


class FreyaAssistant:
    def __init__(self):
        self.memory = MemoryManager()

        self.messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            }
        ]

    def respond(self, user_input):
        if user_input.lower().startswith("remember "):
            memory = user_input[9:].strip()

            if memory:
                self.memory.add_memory(memory)

                return f"I'll remember that: {memory}"

        relevant_memories = self.memory.search_memories(
            user_input
        )

        messages_for_model = self.messages.copy()

        if relevant_memories:
            memory_text = "\n".join(
                f"- {memory}"
                for memory in relevant_memories
            )

            messages_for_model.append(
                {
                    "role": "system",
                    "content": (
                        "Relevant long-term memories:\n"
                        f"{memory_text}"
                    ),
                }
            )

        messages_for_model.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        reply = chat(messages_for_model)

        self.messages.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        self.messages.append(
            {
                "role": "assistant",
                "content": reply,
            }
        )

        return reply