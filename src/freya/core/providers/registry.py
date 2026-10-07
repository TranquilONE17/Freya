from typing import Dict, List, Optional

from freya.core.providers.provider import (
    ProviderDefinition,
    ProviderHealth,
    ProviderOperationResult,
    ProviderState,
)


class ProviderRegistry:
    """
    Tracks providers known to Freya Core.

    The registry manages:
        - provider identity
        - node identity
        - advertised capabilities
        - provider health
        - lifecycle state
        - lifecycle failure isolation

    Provider-specific logic belongs in the provider,
    not in this registry.
    """

    def __init__(self):
        self._providers: Dict[
            str,
            ProviderDefinition,
        ] = {}

    @staticmethod
    def _normalize_id(
        provider_id: str,
    ) -> str:
        return provider_id.strip().lower()

    def register(
        self,
        provider: ProviderDefinition,
    ) -> None:
        """
        Register or replace a provider.
        """

        provider_id = self._normalize_id(
            provider.provider_id
        )

        if not provider_id:
            raise ValueError(
                "Provider ID cannot be empty."
            )

        provider.provider_id = provider_id

        provider.capabilities = [
            capability.strip().lower()
            for capability
            in provider.capabilities
        ]

        self._providers[
            provider_id
        ] = provider

    def unregister(
        self,
        provider_id: str,
    ) -> bool:
        """
        Remove a provider from the registry.
        """

        provider_id = self._normalize_id(
            provider_id
        )

        return (
            self._providers.pop(
                provider_id,
                None,
            )
            is not None
        )

    def exists(
        self,
        provider_id: str,
    ) -> bool:
        """
        Return True if a provider is registered.
        """

        provider_id = self._normalize_id(
            provider_id
        )

        return provider_id in self._providers

    def get(
        self,
        provider_id: str,
    ) -> Optional[ProviderDefinition]:
        """
        Retrieve a provider definition.
        """

        provider_id = self._normalize_id(
            provider_id
        )

        return self._providers.get(
            provider_id
        )

    def list_providers(
        self,
    ) -> List[ProviderDefinition]:
        """
        Return all registered providers.
        """

        return list(
            self._providers.values()
        )

    def providers_for_capability(
        self,
        capability_name: str,
    ) -> List[ProviderDefinition]:
        """
        Return providers advertising a capability.
        """

        capability_name = (
            capability_name.strip().lower()
        )

        return [
            provider
            for provider
            in self._providers.values()
            if capability_name
            in provider.capabilities
        ]

    def set_health(
        self,
        provider_id: str,
        health: ProviderHealth,
    ) -> bool:
        """
        Manually update provider health.
        """

        provider = self.get(
            provider_id
        )

        if provider is None:
            return False

        provider.health = health

        return True

    def set_state(
        self,
        provider_id: str,
        state: ProviderState,
    ) -> bool:
        """
        Manually update provider lifecycle state.
        """

        provider = self.get(
            provider_id
        )

        if provider is None:
            return False

        provider.state = state

        return True

    def is_usable(
        self,
        provider_id: str,
    ) -> bool:
        """
        A provider is automatically usable only when
        it is both RUNNING and HEALTHY.
        """

        provider = self.get(
            provider_id
        )

        if provider is None:
            return False

        return (
            provider.state
            == ProviderState.RUNNING
            and provider.health
            == ProviderHealth.HEALTHY
        )

    def start(
        self,
        provider_id: str,
    ) -> ProviderOperationResult:
        """
        Start a provider through its lifecycle handler.

        Provider exceptions are contained and converted
        into structured failures.
        """

        provider = self.get(
            provider_id
        )

        if provider is None:
            return ProviderOperationResult(
                success=False,
                provider_id=self._normalize_id(
                    provider_id
                ),
                operation="start",
                error="Provider is not registered.",
            )

        if (
            provider.state
            == ProviderState.DISABLED
        ):
            return ProviderOperationResult(
                success=False,
                provider_id=provider.provider_id,
                operation="start",
                error="Provider is disabled.",
            )

        if provider.start_handler is None:
            return ProviderOperationResult(
                success=False,
                provider_id=provider.provider_id,
                operation="start",
                error=(
                    "Provider does not define "
                    "a start handler."
                ),
            )

        provider.state = (
            ProviderState.STARTING
        )

        try:
            result = provider.start_handler()

            provider.state = (
                ProviderState.RUNNING
            )

            return ProviderOperationResult(
                success=True,
                provider_id=provider.provider_id,
                operation="start",
                result=result,
            )

        except Exception as exc:
            provider.state = (
                ProviderState.FAILED
            )

            provider.health = (
                ProviderHealth.UNHEALTHY
            )

            return ProviderOperationResult(
                success=False,
                provider_id=provider.provider_id,
                operation="start",
                error=str(exc),
            )

    def stop(
        self,
        provider_id: str,
    ) -> ProviderOperationResult:
        """
        Stop a provider through its lifecycle handler.
        """

        provider = self.get(
            provider_id
        )

        if provider is None:
            return ProviderOperationResult(
                success=False,
                provider_id=self._normalize_id(
                    provider_id
                ),
                operation="stop",
                error="Provider is not registered.",
            )

        if provider.stop_handler is None:
            return ProviderOperationResult(
                success=False,
                provider_id=provider.provider_id,
                operation="stop",
                error=(
                    "Provider does not define "
                    "a stop handler."
                ),
            )

        provider.state = (
            ProviderState.STOPPING
        )

        try:
            result = provider.stop_handler()

            provider.state = (
                ProviderState.STOPPED
            )

            return ProviderOperationResult(
                success=True,
                provider_id=provider.provider_id,
                operation="stop",
                result=result,
            )

        except Exception as exc:
            provider.state = (
                ProviderState.FAILED
            )

            provider.health = (
                ProviderHealth.UNHEALTHY
            )

            return ProviderOperationResult(
                success=False,
                provider_id=provider.provider_id,
                operation="stop",
                error=str(exc),
            )

    def check_health(
        self,
        provider_id: str,
    ) -> ProviderOperationResult:
        """
        Ask a provider to report its health.

        Phase 1B health handlers may return:
            True
            False
            ProviderHealth
        """

        provider = self.get(
            provider_id
        )

        if provider is None:
            return ProviderOperationResult(
                success=False,
                provider_id=self._normalize_id(
                    provider_id
                ),
                operation="health",
                error="Provider is not registered.",
            )

        if provider.health_handler is None:
            return ProviderOperationResult(
                success=False,
                provider_id=provider.provider_id,
                operation="health",
                error=(
                    "Provider does not define "
                    "a health handler."
                ),
            )

        try:
            result = provider.health_handler()

            if isinstance(
                result,
                ProviderHealth,
            ):
                provider.health = result

            elif result is True:
                provider.health = (
                    ProviderHealth.HEALTHY
                )

            elif result is False:
                provider.health = (
                    ProviderHealth.UNHEALTHY
                )

            else:
                provider.health = (
                    ProviderHealth.UNKNOWN
                )

            return ProviderOperationResult(
                success=True,
                provider_id=provider.provider_id,
                operation="health",
                result=provider.health,
            )

        except Exception as exc:
            provider.health = (
                ProviderHealth.UNHEALTHY
            )

            return ProviderOperationResult(
                success=False,
                provider_id=provider.provider_id,
                operation="health",
                error=str(exc),
            )

    def describe_providers(
        self,
    ) -> List[dict]:
        """
        Return serializable provider information.
        """

        descriptions = []

        for provider in (
            self.list_providers()
        ):
            descriptions.append(
                {
                    "provider_id": (
                        provider.provider_id
                    ),
                    "name": provider.name,
                    "node_id": provider.node_id,
                    "capabilities": list(
                        provider.capabilities
                    ),
                    "health": (
                        provider.health.value
                    ),
                    "state": (
                        provider.state.value
                    ),
                    "metadata": dict(
                        provider.metadata
                    ),
                }
            )

        return descriptions