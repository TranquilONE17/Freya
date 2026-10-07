from dataclasses import dataclass
from typing import List

from freya.config import AUDIT_CHECKPOINT_PATH
from freya.core.audit import (
    AuditStartup,
    FileCheckpointSink,
    SqliteAuditLog,
)
from freya.core.capabilities import (
    LOCAL_OWNER,
    CapabilityBroker,
    CapabilityRegistry,
)
from freya.core.persistence import (
    CONTROL_DATABASE_PATH,
    ControlStore,
)
from freya.core.policy import (
    SqlitePolicyEngine,
    seed_alpha_policy,
)
from freya.core.providers import (
    ProviderRegistry,
)
from freya.tools.system_tools import (
    SYSTEM_TOOL_CAPABILITIES,
    SYSTEM_TOOLS_PROVIDER,
    create_system_tools_provider,
    register_system_tools,
)


@dataclass
class ControlPlane:
    """
    The pieces that stand between a request and a capability.
    """

    store: ControlStore
    providers: ProviderRegistry
    capabilities: CapabilityRegistry
    policy: SqlitePolicyEngine
    audit: SqliteAuditLog
    broker: CapabilityBroker
    audit_startup: AuditStartup

    def startup_messages(self) -> List[str]:
        """
        Things the operator should be told about the audit log.
        """
        verification = self.audit_startup.verification
        messages = []

        if not verification.ok:
            messages.append(
                "AUDIT LOG FAILED VERIFICATION. Tools are disabled "
                "until this is resolved."
            )
            messages.extend(
                f"  - {problem}"
                for problem in verification.problems[:10]
            )

        messages.extend(
            f"Audit warning: {warning}"
            for warning in verification.warnings
        )

        if self.audit_startup.reconciled:
            messages.append(
                f"Audit: {self.audit_startup.reconciled} interrupted "
                "operation(s) were recorded as unknown-outcome."
            )

        return messages

    def close(self) -> None:
        try:
            if self.audit.integrity_ok:
                self.audit.checkpoint()
        finally:
            self.store.close()


def build_local_control_plane(
    database_path=CONTROL_DATABASE_PATH,
    checkpoint_path=AUDIT_CHECKPOINT_PATH,
) -> ControlPlane:
    """
    Assemble the single-workstation control plane: providers,
    capabilities, policy, audit, and the broker in front of them.
    """
    store = ControlStore(database_path)

    providers = ProviderRegistry()
    providers.register(create_system_tools_provider())
    providers.start(SYSTEM_TOOLS_PROVIDER)
    providers.check_health(SYSTEM_TOOLS_PROVIDER)

    capabilities = CapabilityRegistry(providers)
    register_system_tools(capabilities)

    policy = SqlitePolicyEngine(store)
    seed_alpha_policy(
        policy,
        LOCAL_OWNER.actor,
        SYSTEM_TOOL_CAPABILITIES,
    )

    sink = (
        FileCheckpointSink(checkpoint_path)
        if checkpoint_path
        else None
    )
    audit = SqliteAuditLog(store, sink=sink)
    audit_startup = audit.start()

    broker = CapabilityBroker(
        capabilities,
        policy,
        audit,
        LOCAL_OWNER,
    )

    return ControlPlane(
        store=store,
        providers=providers,
        capabilities=capabilities,
        policy=policy,
        audit=audit,
        broker=broker,
        audit_startup=audit_startup,
    )
