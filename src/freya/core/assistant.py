from config import SYSTEM_PROMPT
from core.llm import chat
from memory.memory_manager import MemoryManager


class FreyaAssistant:
    def __init__(self):
        self.memory = MemoryManager()

        memories = self.memory.get_memories()

        memory_text = "\n".join(
            f"- {memory}" for memory in memories
        )

        if not memory_text:
            memory_text = "No saved memories yet."

        self.messages = [
            {
                "role": "system",
                "content": (
                    f"{SYSTEM_PROMPT}\n\n"
                    "Long-term memories:\n"
                    f"{memory_text}"
                ),
            }
        ]

    def respond(self, user_input):
        if user_input.lower().startswith("remember "):
            memory = user_input[9:].strip()

            if memory:
                self.memory.add_memory(memory)

                self.messages[0]["content"] += f"\n- {memory}"

                return f"I'll remember that: {memory}"

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