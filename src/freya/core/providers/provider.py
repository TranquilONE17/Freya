from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class ProviderHealth(str, Enum):
    """
    Health of a provider from Freya Core's perspective.
    """

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"


class ProviderState(str, Enum):
    """
    Lifecycle state of a provider.
    """

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"
    DISABLED = "disabled"


@dataclass
class ProviderDefinition:
    """
    Describes a provider that supplies one or more
    capabilities to Freya.

    Examples:
        ollama-local
        whisper-local
        kokoro-local
        comfyui-local
        system-tools-local

    A provider may eventually run:
        - inside the current Freya process
        - in another local process
        - on another computer
        - on dedicated hardware
    """

    provider_id: str
    name: str

    node_id: str = "local"

    capabilities: List[str] = field(
        default_factory=list
    )

    health: ProviderHealth = (
        ProviderHealth.UNKNOWN
    )

    state: ProviderState = (
        ProviderState.STOPPED
    )

    start_handler: Optional[
        Callable[[], Any]
    ] = None

    stop_handler: Optional[
        Callable[[], Any]
    ] = None

    health_handler: Optional[
        Callable[[], Any]
    ] = None

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class ProviderOperationResult:
    """
    Standard result returned by provider lifecycle
    operations.
    """

    success: bool
    provider_id: str
    operation: str

    result: Any = None
    error: Optional[str] = None