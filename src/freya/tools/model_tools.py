import json
from typing import Any, List


# Metadata key marking a capability the language model may call by
# itself during a conversation.
MODEL_TOOL = "model_tool"

# Metadata key declaring the arguments a model tool accepts:
#     {name: {"description": str, "max_length": int}}
# Every declared argument is a required piece of text. A tool without
# this key takes no arguments.
TOOL_PARAMETERS = "tool_parameters"

DEFAULT_MAX_LENGTH = 1000

TOOL_HINT = (
    "You can call tools. Some read live information about the "
    "computer you are running on: use them whenever the user asks "
    "about this machine's hardware or its current state, and never "
    "guess such values. If an image tool is offered, use it whenever "
    "the user asks you to make, draw, or generate a picture; you "
    "cannot see the result, so do not describe it as if you had. "
    "Answer in plain spoken sentences without Markdown, and do not "
    "read out raw data."
)


class ToolArgumentError(ValueError):
    """
    The model's arguments for a tool were not acceptable. The message
    is written for the model, so it can correct itself.
    """


def validate_arguments(parameters: dict, arguments: Any) -> dict:
    """
    Check what the model supplied against what a tool declared, and
    return only the declared arguments, cleaned.

    The model's arguments are untrusted. Anything the tool did not
    declare is dropped, and every declared argument must be present,
    be text, be non-empty, and fit the declared length.
    """
    if not parameters:
        return {}

    if not isinstance(arguments, dict):
        raise ToolArgumentError(
            "This tool needs arguments: "
            + ", ".join(sorted(parameters))
            + "."
        )

    cleaned = {}

    for name, rules in parameters.items():
        value = arguments.get(name)

        if not isinstance(value, str) or not value.strip():
            raise ToolArgumentError(
                f"The argument '{name}' must be a non-empty piece "
                "of text."
            )

        value = value.strip()
        limit = rules.get("max_length", DEFAULT_MAX_LENGTH)

        if len(value) > limit:
            raise ToolArgumentError(
                f"The argument '{name}' can be at most {limit} "
                "characters."
            )

        cleaned[name] = value

    return cleaned


class ModelToolHost:
    """
    Offers a limited set of capabilities to the language model as
    tools, and runs the ones it asks for.

    Only capabilities explicitly marked as model tools are offered,
    and a destructive capability is never offered or run on the
    model's say-so. Every call goes through the capability broker, so
    policy, availability, and audit apply. A model's request is a
    suggestion: anything it names that is not on offer is refused,
    and its arguments are validated against what the tool declared.
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

    @staticmethod
    def _parameters(capability) -> dict:
        parameters = capability.metadata.get(TOOL_PARAMETERS)

        return parameters if isinstance(parameters, dict) else {}

    def definitions(self) -> List[dict]:
        """
        Tool definitions in the form the chat model expects.
        """
        definitions = []

        for tool_name, capability in self._offered().items():
            parameters = self._parameters(capability)

            schema = {
                "type": "object",
                "properties": {
                    name: {
                        "type": "string",
                        "description": rules.get("description", ""),
                    }
                    for name, rules in parameters.items()
                },
            }

            if parameters:
                schema["required"] = list(parameters)

            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": capability.description,
                        "parameters": schema,
                    },
                }
            )

        return definitions

    def run(self, tool_name: Any, arguments: Any = None) -> str:
        """
        Run one tool the model asked for and return its result as
        JSON text for the model to read. Failures are returned as an
        error object, never raised.
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

        try:
            cleaned = validate_arguments(
                self._parameters(capability),
                arguments,
            )
        except ToolArgumentError as exc:
            return json.dumps({"error": str(exc)})

        result = self._broker.invoke(capability.name, **cleaned)

        if not result.success:
            return json.dumps(
                {"error": result.error or "The tool failed."}
            )

        return json.dumps(result.result, default=str)
