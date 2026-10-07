from dataclasses import dataclass
from typing import List

from freya.config import AUDIT_CHECKPOINT_PATH
from freya.config import EMBEDDING_MODEL
from freya.config import MODEL
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
from freya.core.model_runtime import (
    ModelRuntime,
    configure_model_runtime,
)
from freya.core.providers import (
    ProviderHealth,
    ProviderRegistry,
)
from freya.providers.model.ollama import (
    OLLAMA_CAPABILITIES,
    OLLAMA_PROVIDER,
    create_ollama_provider,
    register_ollama_capabilities,
    warm_ollama_models,
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
    model_runtime: ModelRuntime

    def warm_models(self) -> None:
        """
        Load the Ollama models ahead of the first request.
        """
        metadata = self.providers.get(OLLAMA_PROVIDER).metadata

        warm_ollama_models(
            metadata["chat_model"],
            metadata["embedding_model"],
        )

    def startup_messages(self) -> List[str]:
        """
        Things the operator should be told at startup.
        """
        verification = self.audit_startup.verification
        messages = []

        health = self.providers.get(OLLAMA_PROVIDER).health

        if health == ProviderHealth.OFFLINE:
            messages.append(
                "Ollama is not reachable. Freya cannot reply until "
                "it is running; she will check again on your next "
                "message."
            )
        elif health != ProviderHealth.HEALTHY:
            messages.append(
                "Ollama is running but a required model is not "
                "installed. Freya cannot reply until both models "
                "are available."
            )

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
        configure_model_runtime(None)

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

    providers.register(create_ollama_provider(MODEL, EMBEDDING_MODEL))
    providers.start(OLLAMA_PROVIDER)
    providers.check_health(OLLAMA_PROVIDER)

    capabilities = CapabilityRegistry(providers)
    register_system_tools(capabilities)
    register_ollama_capabilities(capabilities, MODEL, EMBEDDING_MODEL)

    policy = SqlitePolicyEngine(store)
    seed_alpha_policy(
        policy,
        "alpha-system-tools",
        LOCAL_OWNER.actor,
        SYSTEM_TOOL_CAPABILITIES,
    )
    seed_alpha_policy(
        policy,
        "alpha-model-runtime",
        LOCAL_OWNER.actor,
        OLLAMA_CAPABILITIES,
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

    # Everything in this process that needs model work asks for it
    # through the broker.
    model_runtime = ModelRuntime(
        broker,
        refresh_health=lambda: providers.check_health(OLLAMA_PROVIDER),
    )
    configure_model_runtime(model_runtime)

    return ControlPlane(
        model_runtime=model_runtime,
        store=store,
        providers=providers,
        capabilities=capabilities,
        policy=policy,
        audit=audit,
        broker=broker,
        audit_startup=audit_startup,
    )
