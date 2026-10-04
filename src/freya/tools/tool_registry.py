from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolDefinition:
    """
    Describes one tool that Freya can use.
    """

    name: str
    description: str
    handler: Callable[..., Any]

    category: str = "general"

    requires_gpu: bool = False
    destructive: bool = False

    aliases: List[str] = field(
        default_factory=list
    )


@dataclass
class ToolExecutionResult:
    """
    Standard result returned by the tool registry.
    """

    success: bool
    tool_name: str

    result: Any = None
    error: Optional[str] = None


class ToolRegistry:
    """
    Central registry for Freya's tools.

    Responsibilities:
        - register tools
        - retrieve tool definitions
        - list available tools
        - execute registered tools
        - return standardized execution results
    """

    def __init__(self):
        self._tools: Dict[
            str,
            ToolDefinition,
        ] = {}

        self._aliases: Dict[
            str,
            str,
        ] = {}

    def register(
        self,
        tool: ToolDefinition,
    ):
        """
        Register a tool with Freya.
        """

        normalized_name = self._normalize_name(
            tool.name
        )

        if not normalized_name:
            raise ValueError(
                "Tool name cannot be empty."
            )

        if normalized_name in self._tools:
            raise ValueError(
                "Tool is already registered: "
                f"{tool.name}"
            )

        self._tools[
            normalized_name
        ] = tool

        for alias in tool.aliases:
            normalized_alias = (
                self._normalize_name(alias)
            )

            if not normalized_alias:
                continue

            if normalized_alias in self._tools:
                raise ValueError(
                    "Tool alias conflicts with "
                    "registered tool: "
                    f"{alias}"
                )

            existing = self._aliases.get(
                normalized_alias
            )

            if existing is not None:
                raise ValueError(
                    "Tool alias is already registered: "
                    f"{alias}"
                )

            self._aliases[
                normalized_alias
            ] = normalized_name

    def unregister(
        self,
        name: str,
    ):
        """
        Remove a registered tool.
        """

        normalized_name = (
            self._resolve_name(name)
        )

        if normalized_name is None:
            return False

        tool = self._tools.pop(
            normalized_name
        )

        aliases_to_remove = []

        for alias, target in (
            self._aliases.items()
        ):
            if target == normalized_name:
                aliases_to_remove.append(
                    alias
                )

        for alias in aliases_to_remove:
            self._aliases.pop(
                alias,
                None,
            )

        return tool is not None

    def get(
        self,
        name: str,
    ) -> Optional[ToolDefinition]:
        """
        Retrieve a tool by name or alias.
        """

        normalized_name = (
            self._resolve_name(name)
        )

        if normalized_name is None:
            return None

        return self._tools.get(
            normalized_name
        )

    def exists(
        self,
        name: str,
    ) -> bool:
        """
        Check whether a tool exists.
        """

        return self.get(name) is not None

    def list_tools(
        self,
    ) -> List[ToolDefinition]:
        """
        Return all registered tools.
        """

        return list(
            self._tools.values()
        )

    def execute(
        self,
        name: str,
        *args,
        **kwargs,
    ) -> ToolExecutionResult:
        """
        Execute a registered tool.

        Exceptions raised by tool handlers are captured
        and returned as standardized failures.
        """

        tool = self.get(name)

        if tool is None:
            return ToolExecutionResult(
                success=False,
                tool_name=name,
                error=(
                    "Unknown tool: "
                    f"{name}"
                ),
            )

        try:
            result = tool.handler(
                *args,
                **kwargs,
            )

        except Exception as exc:
            return ToolExecutionResult(
                success=False,
                tool_name=tool.name,
                error=str(exc),
            )

        return ToolExecutionResult(
            success=True,
            tool_name=tool.name,
            result=result,
        )

    def describe_tools(
        self,
    ) -> List[dict]:
        """
        Return simple metadata suitable for diagnostics
        and, later, LLM tool-selection prompts.
        """

        descriptions = []

        for tool in self.list_tools():
            descriptions.append(
                {
                    "name": tool.name,
                    "description": (
                        tool.description
                    ),
                    "category": tool.category,
                    "requires_gpu": (
                        tool.requires_gpu
                    ),
                    "destructive": (
                        tool.destructive
                    ),
                    "aliases": list(
                        tool.aliases
                    ),
                }
            )

        return descriptions

    def _resolve_name(
        self,
        name: str,
    ) -> Optional[str]:
        normalized_name = (
            self._normalize_name(name)
        )

        if normalized_name in self._tools:
            return normalized_name

        return self._aliases.get(
            normalized_name
        )

    @staticmethod
    def _normalize_name(
        name: str,
    ) -> str:
        return name.strip().lower()