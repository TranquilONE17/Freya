import json
from dataclasses import dataclass
from typing import Optional

import ollama


@dataclass
class ToolSelection:
    """
    Represents the LLM's decision about whether
    Freya should use a registered tool.
    """

    use_tool: bool
    tool: Optional[str]
    confidence: float
    reason: str = ""


class LLMToolSelector:
    """
    Uses Freya's local LLM to decide whether a user's
    request should be handled by a registered tool.

    Stage 2A is decision-only:
        - it does NOT execute tools
        - it does NOT modify the registry
        - it does NOT perform system actions
    """

    def __init__(
        self,
        registry,
        model="gpt-oss:20b",
    ):
        self.registry = registry
        self.model = model

    def select(
        self,
        user_input: str,
    ) -> ToolSelection:
        """
        Decide whether a registered tool should be used.
        """

        user_input = user_input.strip()

        if not user_input:
            return ToolSelection(
                use_tool=False,
                tool=None,
                confidence=1.0,
                reason="Empty input.",
            )

        tools = self.registry.describe_tools()

        if not tools:
            return ToolSelection(
                use_tool=False,
                tool=None,
                confidence=1.0,
                reason="No tools are registered.",
            )

        prompt = self._build_prompt(
            user_input,
            tools,
        )

        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are Freya's tool-selection "
                            "engine. Your only job is to "
                            "decide whether a registered tool "
                            "is needed for the user's request."
                        ),
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                format="json",
                options={
                    "temperature": 0,
                },
            )

            content = response[
                "message"
            ][
                "content"
            ]

            decision = json.loads(
                content
            )

            return self._validate_decision(
                decision
            )

        except Exception as exc:
            return ToolSelection(
                use_tool=False,
                tool=None,
                confidence=0.0,
                reason=(
                    "Tool selection failed safely: "
                    f"{exc}"
                ),
            )

    def _build_prompt(
        self,
        user_input,
        tools,
    ):
        """
        Build the tool-selection prompt.
        """

        tool_descriptions = []

        for tool in tools:
            tool_descriptions.append(
                {
                    "name": tool["name"],
                    "description": (
                        tool["description"]
                    ),
                    "category": (
                        tool["category"]
                    ),
                }
            )

        return (
            "Decide whether the user's request requires "
            "one of the available tools.\n\n"
            "AVAILABLE TOOLS:\n"
            f"{json.dumps(tool_descriptions, indent=2)}"
            "\n\n"
            "USER REQUEST:\n"
            f"{user_input}\n\n"
            "RULES:\n"
            "1. Select a tool only when live, local, "
            "machine-specific information is required.\n"
            "2. Do not select a tool for ordinary "
            "conversation, general knowledge, writing, "
            "brainstorming, or questions the assistant "
            "can answer without live machine data.\n"
            "3. You may only select a tool whose exact "
            "name appears in AVAILABLE TOOLS.\n"
            "4. If no tool is appropriate, set "
            "use_tool to false and tool to null.\n"
            "5. confidence must be a number from "
            "0.0 through 1.0.\n"
            "6. Keep reason short.\n\n"
            "Return ONLY a JSON object with this shape:\n"
            "{\n"
            '  "use_tool": true or false,\n'
            '  "tool": "tool.name" or null,\n'
            '  "confidence": 0.0,\n'
            '  "reason": "short explanation"\n'
            "}"
        )

    def _validate_decision(
        self,
        decision,
    ) -> ToolSelection:
        """
        Validate the LLM response before trusting it.

        An invalid or hallucinated tool selection fails
        closed and becomes a no-tool decision.
        """

        if not isinstance(
            decision,
            dict,
        ):
            return self._safe_failure(
                "LLM returned a non-object response."
            )

        use_tool = decision.get(
            "use_tool",
            False,
        )

        tool_name = decision.get(
            "tool"
        )

        confidence = decision.get(
            "confidence",
            0.0,
        )

        reason = str(
            decision.get(
                "reason",
                "",
            )
        )

        if not isinstance(
            use_tool,
            bool,
        ):
            return self._safe_failure(
                "Invalid use_tool value."
            )

        try:
            confidence = float(
                confidence
            )

        except (
            TypeError,
            ValueError,
        ):
            return self._safe_failure(
                "Invalid confidence value."
            )

        confidence = max(
            0.0,
            min(
                1.0,
                confidence,
            ),
        )

        if not use_tool:
            return ToolSelection(
                use_tool=False,
                tool=None,
                confidence=confidence,
                reason=reason,
            )

        if not isinstance(
            tool_name,
            str,
        ):
            return self._safe_failure(
                "Tool selection did not contain "
                "a valid tool name."
            )

        tool_name = tool_name.strip()

        if not self.registry.exists(
            tool_name
        ):
            return self._safe_failure(
                "LLM selected an unregistered tool: "
                f"{tool_name}"
            )

        tool = self.registry.get(
            tool_name
        )

        return ToolSelection(
            use_tool=True,
            tool=tool.name,
            confidence=confidence,
            reason=reason,
        )

    @staticmethod
    def _safe_failure(
        reason,
    ):
        return ToolSelection(
            use_tool=False,
            tool=None,
            confidence=0.0,
            reason=reason,
        )