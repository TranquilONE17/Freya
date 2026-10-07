from typing import Dict, List, Optional

from freya.core.capabilities.capability import (
    CapabilityDefinition,
    CapabilityExecutionResult,
    CapabilityStatus,
)


class CapabilityRegistry:
    """
    Central registry describing what Freya can currently do.

    The registry intentionally depends on capability
    contracts rather than specific implementations.

    Providers may eventually live:
        - in the current process
        - in another local process
        - on another machine
        - on dedicated GPU hardware
        - behind an API

    Freya Core should not need to know the difference.
    """

    def __init__(self):
        self._capabilities: Dict[
            str,
            CapabilityDefinition,
        ] = {}

    @staticmethod
    def _normalize_name(
        name: str,
    ) -> str:
        return name.strip().lower()

    def register(
        self,
        capability: CapabilityDefinition,
    ) -> None:
        """
        Register or replace a capability.
        """

        name = self._normalize_name(
            capability.name
        )

        if not name:
            raise ValueError(
                "Capability name cannot be empty."
            )

        capability.name = name

        self._capabilities[name] = capability

    def unregister(
        self,
        name: str,
    ) -> bool:
        """
        Remove a capability from the registry.
        """

        name = self._normalize_name(name)

        return (
            self._capabilities.pop(
                name,
                None,
            )
            is not None
        )

    def exists(
        self,
        name: str,
    ) -> bool:
        """
        Return True when a capability is registered.
        """

        name = self._normalize_name(name)

        return name in self._capabilities

    def get(
        self,
        name: str,
    ) -> Optional[CapabilityDefinition]:
        """
        Retrieve a capability definition.
        """

        name = self._normalize_name(name)

        return self._capabilities.get(name)

    def list_capabilities(
        self,
    ) -> List[CapabilityDefinition]:
        """
        Return all registered capabilities.
        """

        return list(
            self._capabilities.values()
        )

    def set_status(
        self,
        name: str,
        status: CapabilityStatus,
    ) -> bool:
        """
        Change the runtime status of a capability.
        """

        capability = self.get(name)

        if capability is None:
            return False

        capability.status = status

        return True

    def is_available(
        self,
        name: str,
    ) -> bool:
        """
        Return True only when a capability exists and
        is currently marked AVAILABLE.
        """

        capability = self.get(name)

        if capability is None:
            return False

        return (
            capability.status
            == CapabilityStatus.AVAILABLE
        )

    def execute(
        self,
        name: str,
        *args,
        **kwargs,
    ) -> CapabilityExecutionResult:
        """
        Execute an available capability.

        Exceptions from one provider are contained here
        and returned as structured failures rather than
        being allowed to crash unrelated Freya systems.
        """

        capability = self.get(name)

        if capability is None:
            return CapabilityExecutionResult(
                success=False,
                capability_name=(
                    self._normalize_name(name)
                ),
                error=(
                    "Capability is not registered."
                ),
            )

        if (
            capability.status
            != CapabilityStatus.AVAILABLE
        ):
            return CapabilityExecutionResult(
                success=False,
                capability_name=capability.name,
                provider=capability.provider,
                error=(
                    "Capability is not available. "
                    f"Current status: "
                    f"{capability.status.value}"
                ),
            )

        try:
            result = capability.handler(
                *args,
                **kwargs,
            )

            return CapabilityExecutionResult(
                success=True,
                capability_name=capability.name,
                provider=capability.provider,
                result=result,
            )

        except Exception as exc:
            return CapabilityExecutionResult(
                success=False,
                capability_name=capability.name,
                provider=capability.provider,
                error=str(exc),
            )

    def describe_capabilities(
        self,
    ) -> List[dict]:
        """
        Return serializable capability metadata.

        This will later be useful for:
            - Freya planning
            - diagnostics
            - remote nodes
            - admin interfaces
            - capability discovery
        """

        descriptions = []

        for capability in (
            self.list_capabilities()
        ):
            descriptions.append(
                {
                    "name": capability.name,
                    "description": (
                        capability.description
                    ),
                    "provider": (
                        capability.provider
                    ),
                    "category": (
                        capability.category
                    ),
                    "status": (
                        capability.status.value
                    ),
                    "optional_dependencies": list(
                        capability.optional_dependencies
                    ),
                    "metadata": dict(
                        capability.metadata
                    ),
                }
            )

        return descriptions