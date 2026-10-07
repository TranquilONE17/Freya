import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from freya.core.capabilities.capability import (
    CapabilityStatus,
)
from freya.core.policy.engine import (
    PolicyDecision,
)


@dataclass(frozen=True)
class Principal:
    """
    Who an invocation is performed for. Core decides this when it
    builds the broker; callers of invoke() cannot supply or change it.
    """

    actor: str
    client: str
    domain: str


# Until authenticated sessions exist, everything the CLI does is
# attributed to the single local owner.
LOCAL_OWNER = Principal(
    actor="local-owner",
    client="cli",
    domain="local",
)


@dataclass
class BrokerResult:
    """
    Result of asking the broker to invoke a capability.

    outcome is one of: succeeded, failed-known, unknown-outcome,
    denied, unavailable.
    """

    success: bool
    capability_name: str
    operation_id: str
    outcome: str
    provider: Optional[str] = None
    result: Any = None
    error: Optional[str] = None


def _arguments_digest(args, kwargs) -> str:
    canonical = json.dumps(
        [list(args), kwargs],
        sort_keys=True,
        default=repr,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CapabilityBroker:
    """
    The single path for invoking a capability.

    Each invocation is, in order: authorized by policy (deny by
    default), checked for availability, recorded in the audit log,
    executed, and has its outcome recorded. If policy cannot be read
    or the pre-execution audit record cannot be written, the
    capability is not executed.
    """

    def __init__(
        self,
        registry,
        policy,
        audit,
        principal: Principal = LOCAL_OWNER,
    ):
        self._registry = registry
        self._policy = policy
        self._audit = audit
        self._principal = principal

    def exists(self, name: str) -> bool:
        return self._registry.exists(name)

    def invoke(
        self,
        name: str,
        *args,
        **kwargs,
    ) -> BrokerResult:
        operation_id = uuid.uuid4().hex

        capability = self._registry.get(name)
        capability_name = (
            capability.name
            if capability is not None
            else name.strip().lower()
        )
        provider = (
            capability.provider
            if capability is not None
            else None
        )

        def result(outcome, error=None, value=None):
            return BrokerResult(
                success=outcome == "succeeded",
                capability_name=capability_name,
                operation_id=operation_id,
                outcome=outcome,
                provider=provider,
                result=value,
                error=error,
            )

        if capability is None:
            decision = PolicyDecision(
                allow=False,
                reason="Capability is not registered.",
            )
        else:
            try:
                decision = self._policy.decide(
                    self._principal.actor,
                    capability_name,
                )
            except Exception:
                decision = PolicyDecision(
                    allow=False,
                    reason="Policy state is unavailable.",
                )

        event = {
            "operation_id": operation_id,
            "actor": self._principal.actor,
            "client": self._principal.client,
            "domain": self._principal.domain,
            "capability": capability_name,
            "provider": provider,
            "decision": "allow" if decision.allow else "deny",
            "decision_reason": decision.reason,
            "policy_revision": decision.revision,
            "grant_epoch": decision.grant_epoch,
            "arguments_digest": _arguments_digest(args, kwargs),
        }

        if not decision.allow:
            self._record_quietly(
                event,
                kind="decision",
                outcome="denied",
            )
            return result(
                "denied",
                error=f"Not authorized: {decision.reason}",
            )

        status = self._registry.get_status(capability_name)

        if status != CapabilityStatus.AVAILABLE:
            error = (
                "Capability is not available. "
                f"Current status: {status.value}"
            )
            self._record_quietly(
                event,
                kind="decision",
                outcome="unavailable",
                error_summary=error,
            )
            return result("unavailable", error=error)

        try:
            self._audit.record(kind="dispatch", **event)
        except Exception as exc:
            return result(
                "denied",
                error=(
                    "Not performed because the action could not be "
                    f"recorded in the audit log: {exc}"
                ),
            )

        execution = self._registry.execute(
            capability_name,
            *args,
            **kwargs,
        )

        if execution.success:
            outcome = "succeeded"
        elif capability.destructive:
            # A destructive action that raised may still have had
            # an effect.
            outcome = "unknown-outcome"
        else:
            outcome = "failed-known"

        # If this write fails, the operation is closed out as
        # unknown-outcome when the audit log next starts.
        self._record_quietly(
            event,
            kind="outcome",
            outcome=outcome,
            error_summary=execution.error,
        )

        return result(
            outcome,
            error=execution.error,
            value=execution.result,
        )

    def _record_quietly(self, event, **fields):
        try:
            self._audit.record(**event, **fields)
        except Exception:
            pass
