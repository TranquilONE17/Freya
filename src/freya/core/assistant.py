from config import SYSTEM_PROMPT
from core.llm import chat, evaluate_memory
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
        command_response = self._handle_memory_command(
            user_input
        )

        if command_response is not None:
            return command_response

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

        memory = evaluate_memory(user_input)

        if memory:
            self.memory.add_memory(memory)

        return reply

    def _handle_memory_command(self, user_input):
        stripped_input = user_input.strip()
        lower_input = stripped_input.lower()

        if lower_input == "/memory-help":
            return (
                "Memory commands:\n"
                "/memories - Show saved memories\n"
                "/remember <text> - Save a memory\n"
                "/forget <ID> - Delete a memory\n"
                "/memory-help - Show these commands"
            )

        if lower_input == "/memories":
            memories = self.memory.get_all_memories()

            if not memories:
                return "I don't have any saved memories yet."

            lines = ["Saved memories:"]

            for memory_id, content, created_at in memories:
                lines.append(
                    f"[{memory_id}] {content} "
                    f"({created_at})"
                )

            return "\n".join(lines)

        if lower_input.startswith("/remember "):
            memory = stripped_input[
                len("/remember "):
            ].strip()

            if not memory:
                return (
                    "Tell me what you'd like me to remember."
                )

            memory_id = self.memory.add_memory(
                memory
            )

            return (
                f"I'll remember that. "
                f"Memory ID: {memory_id}"
            )

        if lower_input.startswith("/forget "):
            memory_id_text = stripped_input[
                len("/forget "):
            ].strip()

            try:
                memory_id = int(memory_id_text)

            except ValueError:
                return (
                    "Please provide the numeric memory ID. "
                    "Use /memories to see the IDs."
                )

            deleted = self.memory.delete_memory(
                memory_id
            )

            if deleted:
                return (
                    f"Memory {memory_id} has been deleted."
                )

            return (
                f"I couldn't find memory {memory_id}."
            )

        if lower_input.startswith("remember "):
            memory = stripped_input[
                len("remember "):
            ].strip()

            if memory:
                memory_id = self.memory.add_memory(
                    memory
                )

                return (
                    f"I'll remember that. "
                    f"Memory ID: {memory_id}"
                )

        return None