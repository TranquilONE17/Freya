from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class CapabilityStatus(str, Enum):
    """
    Runtime availability state of a capability.
    """

    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


@dataclass
class CapabilityDefinition:
    """
    Describes one capability available to Freya.

    A capability represents WHAT Freya can do.

    Examples:
        llm.chat
        memory.search
        speech.transcribe
        speech.synthesize
        image.generate
        tools.execute

    The implementation behind a capability may later be
    local, remote, hardware-specific, or replaceable.
    """

    name: str
    description: str

    provider: str
    handler: Callable[..., Any]

    category: str = "general"

    status: CapabilityStatus = CapabilityStatus.AVAILABLE

    optional_dependencies: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


@dataclass
class CapabilityExecutionResult:
    """
    Standard result returned when Freya invokes a capability.
    """

    success: bool
    capability_name: str

    provider: Optional[str] = None

    result: Any = None
    error: Optional[str] = None