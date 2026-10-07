from dataclasses import dataclass
from pathlib import Path
from typing import List

from freya.config import AUDIT_CHECKPOINT_PATH
from freya.config import COMFYUI_COMMAND
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
    CapabilityDefinition,
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
    ProviderDefinition,
    ProviderHealth,
    ProviderRegistry,
    ProviderState,
)
from freya.image.image_generator import (
    COMFYUI_URL,
)
from freya.providers.image.comfyui import (
    COMFYUI_PROVIDER,
    IMAGE_GENERATE,
    ComfyUIServer,
    create_comfyui_provider,
)
from freya.providers.model.ollama import (
    OLLAMA_CAPABILITIES,
    OLLAMA_PROVIDER,
    create_ollama_provider,
    register_ollama_capabilities,
    warm_ollama_models,
)
from freya.tools.model_tools import (
    MODEL_TOOL,
    TOOL_PARAMETERS,
    ModelToolHost,
)


IMAGE_SERVICE_PROVIDER = "image-service-local"
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
    model_tools: ModelToolHost

    def warm_models(self) -> None:
        """
        Load the Ollama models ahead of the first request.
        """
        metadata = self.providers.get(OLLAMA_PROVIDER).metadata

        warm_ollama_models(
            metadata["chat_model"],
            metadata["embedding_model"],
        )

    def register_image_generation(self, generate) -> None:
        """
        Offer image generation as a capability the model can call.

        The capability belongs to Freya's own image service, which
        starts ComfyUI on demand and hands the GPU back afterwards, so
        it is available whenever ComfyUI is running or can be started.
        """
        comfyui = self.providers.get(COMFYUI_PROVIDER)

        def service_health():
            self.providers.check_health(COMFYUI_PROVIDER)

            return bool(
                comfyui.health == ProviderHealth.HEALTHY
                or comfyui.metadata["can_start"]
            )

        self.providers.register(
            ProviderDefinition(
                provider_id=IMAGE_SERVICE_PROVIDER,
                name="Freya image service",
                capabilities=[IMAGE_GENERATE],
                start_handler=lambda: None,
                health_handler=service_health,
            )
        )
        self.providers.start(IMAGE_SERVICE_PROVIDER)
        self.providers.check_health(IMAGE_SERVICE_PROVIDER)

        self.capabilities.register(
            CapabilityDefinition(
                name=IMAGE_GENERATE,
                description=(
                    "Generates a picture from a text description and "
                    "shows it in the Images tab of Freya's window. "
                    "Use this whenever the user asks for an image, "
                    "picture, drawing, illustration, or photo. It "
                    "takes about twenty seconds."
                ),
                provider=IMAGE_SERVICE_PROVIDER,
                handler=generate,
                category="image",
                requires_gpu=True,
                optional_dependencies=[COMFYUI_PROVIDER],
                metadata={
                    MODEL_TOOL: True,
                    TOOL_PARAMETERS: {
                        "prompt": {
                            "description": (
                                "A detailed description of the "
                                "picture to generate."
                            ),
                            "max_length": 1000,
                        },
                    },
                },
            )
        )

        seed_alpha_policy(
            self.policy,
            "alpha-image-generate",
            LOCAL_OWNER.actor,
            [IMAGE_GENERATE],
        )

    def ensure_image_backend(self, announce=print) -> None:
        """
        Make sure ComfyUI is running, starting it if needed. Raises
        RuntimeError when it is not running and cannot be started.
        """
        self.providers.check_health(COMFYUI_PROVIDER)
        provider = self.providers.get(COMFYUI_PROVIDER)

        if provider.health != ProviderHealth.HEALTHY:
            if provider.metadata["can_start"]:
                announce(
                    "Freya: ComfyUI is not running, so I am starting "
                    "it. This can take a minute..."
                )

                if not provider.metadata["headless"]:
                    announce(
                        "Freya: Its window may need you to press "
                        "its start button."
                    )

            result = self.providers.start(COMFYUI_PROVIDER)

            if not result.success:
                raise RuntimeError(result.error)

            self.providers.check_health(COMFYUI_PROVIDER)
            announce("Freya: ComfyUI is ready.")
            return

        # It was started outside Freya; record that it is up.
        self.providers.set_state(
            COMFYUI_PROVIDER,
            ProviderState.RUNNING,
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

        # Stops the ComfyUI server only if Freya started it.
        self.providers.stop(COMFYUI_PROVIDER)

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

    # ComfyUI is started on demand, when an image is first requested.
    comfyui = ComfyUIServer(
        COMFYUI_URL,
        COMFYUI_COMMAND,
        log_path=Path(database_path).parent / "comfyui_server.log",
    )
    providers.register(create_comfyui_provider(comfyui))

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
    # Tools added after the first seed need a seed of their own, because
    # a seed that has already been applied is never applied again.
    seed_alpha_policy(
        policy,
        "alpha-system-hardware",
        LOCAL_OWNER.actor,
        ["system.cpu", "system.memory", "system.hardware"],
    )
    seed_alpha_policy(
        policy,
        "alpha-system-sensors",
        LOCAL_OWNER.actor,
        ["system.sensors"],
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
        model_tools=ModelToolHost(capabilities, broker),
        store=store,
        providers=providers,
        capabilities=capabilities,
        policy=policy,
        audit=audit,
        broker=broker,
        audit_startup=audit_startup,
    )
