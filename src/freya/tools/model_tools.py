import json
from typing import Any, List


# Metadata key marking a capability the language model may call by
# itself during a conversation.
MODEL_TOOL = "model_tool"

TOOL_HINT = (
    "You can call tools to read live information about the computer "
    "you are running on. Use them whenever the user asks about this "
    "machine's hardware or its current state, and never guess such "
    "values. Answer in plain spoken sentences without Markdown, and "
    "do not read out raw data."
)


class ModelToolHost:
    """
    Offers a limited set of capabilities to the language model as
    tools, and runs the ones it asks for.

    Only capabilities explicitly marked as model tools are offered,
    and a destructive capability is never offered or run on the
    model's say-so. Every call goes through the capability broker, so
    policy, availability, and audit apply. A model's request is a
    suggestion: anything it names that is not on offer is refused.
    """

    # Told to the model whenever tools are offered.
    hint = TOOL_HINT

    def __init__(self, registry, broker):
        self._registry = registry
        self._broker = broker

    @staticmethod
    def _tool_name(capability_name: str) -> str:
        # Function names may not contain dots.
        return capability_name.replace(".", "_")

    def _offered(self) -> dict:
        return {
            self._tool_name(capability.name): capability
            for capability in self._registry.list_capabilities()
            if capability.metadata.get(MODEL_TOOL) is True
            and not capability.destructive
            and self._registry.is_available(capability.name)
        }

    def definitions(self) -> List[dict]:
        """
        Tool definitions in the form the chat model expects.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": capability.description,
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            }
            for tool_name, capability in self._offered().items()
        ]

    def run(self, tool_name: Any, arguments: Any = None) -> str:
        """
        Run one tool the model asked for and return its result as
        JSON text for the model to read. Failures are returned as an
        error object, never raised.

        The offered tools take no arguments, so any the model supplies
        are ignored.
        """
        capability = (
            self._offered().get(tool_name)
            if isinstance(tool_name, str)
            else None
        )

        if capability is None:
            return json.dumps(
                {"error": "That tool is not available."}
            )

        result = self._broker.invoke(capability.name)

        if not result.success:
            return json.dumps(
                {"error": result.error or "The tool failed."}
            )

        return json.dumps(result.result, default=str)
