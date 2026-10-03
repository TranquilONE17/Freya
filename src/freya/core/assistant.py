from config import SYSTEM_PROMPT
from core.llm import (
    chat,
    evaluate_memory,
)
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
        command_response = (
            self._handle_memory_command(
                user_input
            )
        )

        if command_response is not None:
            return command_response

        relevant_memories = (
            self.memory.search_memories(
                user_input
            )
        )

        messages_for_model = (
            self.messages.copy()
        )

        if relevant_memories:
            memory_text = "\n".join(
                (
                    f"- [{memory['type']}] "
                    f"{memory['content']}"
                )
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

        reply = chat(
            messages_for_model
        )

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

        self._process_automatic_memory(
            user_input
        )

        return reply

    def _process_automatic_memory(
        self,
        user_input,
    ):
        candidate = evaluate_memory(
            user_input
        )

        if candidate is None:
            return

        self.memory.process_candidate(
            candidate
        )

    def _handle_memory_command(
        self,
        user_input,
    ):
        stripped_input = user_input.strip()
        lower_input = stripped_input.lower()

        if lower_input == "/memory-help":
            return (
                "Memory commands:\n"
                "/memories - Show saved memories\n"
                "/remember <text> - Save a memory\n"
                "/edit <ID> <text> - Edit a memory\n"
                "/forget <ID> - Delete a memory\n"
                "/memory-history <ID> - Show memory history\n"
                "/memory-help - Show these commands"
            )

        if lower_input == "/memories":
            memories = (
                self.memory.get_all_memories()
            )

            if not memories:
                return (
                    "I don't have any saved "
                    "memories yet."
                )

            lines = ["Saved memories:"]

            for (
                memory_id,
                memory_type,
                memory_key,
                content,
                created_at,
                updated_at,
            ) in memories:

                display_key = (
                    memory_key
                    if memory_key
                    else "unkeyed"
                )

                lines.append(
                    f"[{memory_id}] "
                    f"[{memory_type}] "
                    f"[{display_key}] "
                    f"{content} "
                    f"(created: {created_at}, "
                    f"updated: {updated_at})"
                )

            return "\n".join(lines)

        if lower_input.startswith(
            "/memory-history "
        ):
            memory_id_text = (
                stripped_input[
                    len("/memory-history "):
                ].strip()
            )

            try:
                memory_id = int(
                    memory_id_text
                )
            except ValueError:
                return (
                    "Please provide a numeric "
                    "memory ID."
                )

            history = (
                self.memory.get_memory_history(
                    memory_id
                )
            )

            if not history:
                return (
                    f"Memory {memory_id} "
                    "doesn't have any archived "
                    "history yet."
                )

            lines = [
                f"History for memory {memory_id}:"
            ]

            for (
                history_id,
                archived_memory_id,
                action,
                memory_type,
                memory_key,
                content,
                original_created_at,
                original_updated_at,
                archived_at,
            ) in history:

                display_key = (
                    memory_key
                    if memory_key
                    else "unkeyed"
                )

                lines.append(
                    f"[History {history_id}] "
                    f"[{action}] "
                    f"[{memory_type}] "
                    f"[{display_key}] "
                    f"{content} "
                    f"(original created: "
                    f"{original_created_at}, "
                    f"original updated: "
                    f"{original_updated_at}, "
                    f"archived: {archived_at})"
                )

            return "\n".join(lines)

        if lower_input.startswith(
            "/remember "
        ):
            memory = stripped_input[
                len("/remember "):
            ].strip()

            if not memory:
                return (
                    "Tell me what you'd like "
                    "me to remember."
                )

            candidate = evaluate_memory(
                memory
            )

            if candidate is None:
                memory_id = (
                    self.memory.add_memory(
                        content=memory,
                    )
                )

                return (
                    f"I'll remember that. "
                    f"Memory ID: {memory_id}"
                )

            result = (
                self.memory.process_candidate(
                    candidate
                )
            )

            return (
                f"I'll remember that. "
                f"Memory ID: "
                f"{result['memory_id']}"
            )

        if lower_input.startswith(
            "/edit "
        ):
            edit_text = stripped_input[
                len("/edit "):
            ].strip()

            parts = edit_text.split(
                maxsplit=1
            )

            if len(parts) != 2:
                return (
                    "Use /edit <ID> "
                    "<new memory text>."
                )

            try:
                memory_id = int(
                    parts[0]
                )
            except ValueError:
                return (
                    "Please provide a numeric "
                    "memory ID."
                )

            new_content = parts[1].strip()

            if not new_content:
                return (
                    "Please provide the new "
                    "memory text."
                )

            existing = (
                self.memory.get_memory(
                    memory_id
                )
            )

            if existing is None:
                return (
                    f"I couldn't find memory "
                    f"{memory_id}."
                )

            candidate = evaluate_memory(
                new_content
            )

            if candidate:
                updated = (
                    self.memory.update_memory(
                        memory_id=memory_id,
                        content=candidate[
                            "content"
                        ],
                        memory_type=candidate[
                            "type"
                        ],
                        memory_key=candidate[
                            "key"
                        ],
                        action="manual_edit",
                    )
                )

            else:
                updated = (
                    self.memory.update_memory(
                        memory_id=memory_id,
                        content=new_content,
                        action="manual_edit",
                    )
                )

            if updated:
                return (
                    f"Memory {memory_id} "
                    "has been updated."
                )

            return (
                f"I couldn't update memory "
                f"{memory_id}."
            )

        if lower_input.startswith(
            "/forget "
        ):
            memory_id_text = (
                stripped_input[
                    len("/forget "):
                ].strip()
            )

            try:
                memory_id = int(
                    memory_id_text
                )

            except ValueError:
                return (
                    "Please provide the numeric "
                    "memory ID. Use /memories "
                    "to see the IDs."
                )

            deleted = (
                self.memory.delete_memory(
                    memory_id,
                    action="manual_delete",
                )
            )

            if deleted:
                return (
                    f"Memory {memory_id} "
                    "has been deleted."
                )

            return (
                f"I couldn't find memory "
                f"{memory_id}."
            )

        if lower_input.startswith(
            "remember "
        ):
            memory = stripped_input[
                len("remember "):
            ].strip()

            if memory:
                candidate = evaluate_memory(
                    memory
                )

                if candidate:
                    result = (
                        self.memory.process_candidate(
                            candidate
                        )
                    )

                    return (
                        "I'll remember that. "
                        f"Memory ID: "
                        f"{result['memory_id']}"
                    )

                memory_id = (
                    self.memory.add_memory(
                        content=memory
                    )
                )

                return (
                    "I'll remember that. "
                    f"Memory ID: {memory_id}"
                )

        return None