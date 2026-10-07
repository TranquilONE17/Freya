from dataclasses import dataclass
from typing import Any, Optional

from freya.core.capabilities import (
    CapabilityExecutionResult,
)


@dataclass
class SafeToolExecutionResult:
    """
    Result returned by Freya's safe tool executor.

    This wraps the registry's execution result with
    additional information about whether execution
    was allowed or blocked.
    """

    requested: bool
    executed: bool
    blocked: bool

    tool_name: Optional[str]

    result: Any = None
    error: Optional[str] = None
    reason: str = ""


class SafeToolExecutor:
    """
    Safety layer between Freya's tool selector
    and the CapabilityRegistry.

    Stage 2B policy:

        destructive=False
            Automatic execution is allowed.

        destructive=True
            Automatic execution is blocked.

    The executor never trusts an LLM-selected tool
    name without checking the registry again.
    """

    def __init__(
        self,
        registry,
        minimum_confidence=0.70,
    ):
        self.registry = registry
        self.minimum_confidence = (
            minimum_confidence
        )

    def execute_selection(
        self,
        selection,
    ) -> SafeToolExecutionResult:
        """
        Safely execute a ToolSelection.
        """

        if not selection.use_tool:
            return SafeToolExecutionResult(
                requested=False,
                executed=False,
                blocked=False,
                tool_name=None,
                reason=(
                    "Tool selector decided that "
                    "no tool is required."
                ),
            )

        tool_name = selection.tool

        if not tool_name:
            return SafeToolExecutionResult(
                requested=True,
                executed=False,
                blocked=True,
                tool_name=None,
                error=(
                    "Tool selection did not "
                    "include a tool name."
                ),
                reason=(
                    "Invalid tool selection."
                ),
            )

        if selection.confidence < (
            self.minimum_confidence
        ):
            return SafeToolExecutionResult(
                requested=True,
                executed=False,
                blocked=True,
                tool_name=tool_name,
                error=(
                    "Tool selection confidence "
                    "was below the automatic "
                    "execution threshold."
                ),
                reason=(
                    f"Confidence "
                    f"{selection.confidence:.2f} "
                    f"is below required "
                    f"{self.minimum_confidence:.2f}."
                ),
            )

        tool = self.registry.get(
            tool_name
        )

        if tool is None:
            return SafeToolExecutionResult(
                requested=True,
                executed=False,
                blocked=True,
                tool_name=tool_name,
                error=(
                    "Selected tool is not "
                    "registered."
                ),
                reason=(
                    "Registry validation failed."
                ),
            )

        if tool.destructive:
            return SafeToolExecutionResult(
                requested=True,
                executed=False,
                blocked=True,
                tool_name=tool.name,
                error=(
                    "Automatic execution of "
                    "destructive tools is blocked."
                ),
                reason=(
                    "Tool requires explicit "
                    "authorization."
                ),
            )

        if not self.registry.is_available(
            tool.name
        ):
            return SafeToolExecutionResult(
                requested=True,
                executed=False,
                blocked=True,
                tool_name=tool.name,
                error=(
                    "Selected tool is not "
                    "currently available."
                ),
                reason=(
                    "Capability or its provider "
                    "is not available."
                ),
            )

        registry_result = (
            self.registry.execute(
                tool.name
            )
        )

        return self._convert_result(
            registry_result
        )

    @staticmethod
    def _convert_result(
        registry_result: CapabilityExecutionResult,
    ) -> SafeToolExecutionResult:
        """
        Convert a CapabilityRegistry result into the
        executor's standardized result.
        """

        if registry_result.success:
            return SafeToolExecutionResult(
                requested=True,
                executed=True,
                blocked=False,
                tool_name=(
                    registry_result.capability_name
                ),
                result=(
                    registry_result.result
                ),
                reason=(
                    "Tool executed successfully."
                ),
            )

        return SafeToolExecutionResult(
            requested=True,
            executed=True,
            blocked=False,
            tool_name=(
                registry_result.capability_name
            ),
            error=(
                registry_result.error
            ),
            reason=(
                "Tool execution failed."
            ),
        )
    