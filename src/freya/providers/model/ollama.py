import ollama

from freya.core.capabilities import (
    CapabilityDefinition,
)
from freya.core.model_runtime import (
    LLM_CHAT,
    LLM_CHAT_STREAM,
    LLM_EMBED,
)
from freya.core.providers import (
    ProviderDefinition,
    ProviderHealth,
)


OLLAMA_PROVIDER = "ollama-local"

OLLAMA_CAPABILITIES = [
    LLM_CHAT,
    LLM_CHAT_STREAM,
    LLM_EMBED,
]


def _with_tag(model):
    return model if ":" in model else f"{model}:latest"


def check_ollama_health(models):
    """
    OFFLINE when the Ollama server cannot be reached, UNHEALTHY when
    it is up but a required model is not installed, else HEALTHY.
    """
    try:
        listed = ollama.list()
    except Exception:
        return ProviderHealth.OFFLINE

    installed = {
        _with_tag(entry["model"])
        for entry in listed["models"]
    }

    if all(_with_tag(model) in installed for model in models):
        return ProviderHealth.HEALTHY

    return ProviderHealth.UNHEALTHY


def warm_ollama_models(chat_model, embedding_model):
    """
    Ask Ollama to load both models so the first real request does not
    wait for them. An empty generate request loads a model without
    producing output.
    """
    try:
        ollama.generate(model=chat_model)
        ollama.embed(
            model=embedding_model,
            input="warm-up",
        )
    except Exception:
        # Ollama may not be running yet; the first real call reports that.
        pass


def create_ollama_provider(chat_model, embedding_model):
    """
    Describe the local Ollama server as a model runtime provider.

    Ollama runs as its own service, so Freya has nothing to start or
    stop; the provider is usable whenever the health check passes.
    """
    return ProviderDefinition(
        provider_id=OLLAMA_PROVIDER,
        name="Local Ollama model runtime",
        capabilities=list(OLLAMA_CAPABILITIES),
        start_handler=lambda: None,
        health_handler=lambda: check_ollama_health(
            [chat_model, embedding_model]
        ),
        metadata={
            "chat_model": chat_model,
            "embedding_model": embedding_model,
        },
    )


def register_ollama_capabilities(
    registry,
    chat_model,
    embedding_model,
):
    """
    Register the model capabilities Ollama provides. Callers name the
    capability, never the model or the Ollama client.
    """

    def chat(messages, **options):
        response = ollama.chat(
            model=chat_model,
            messages=messages,
            **options,
        )
        return response["message"]["content"]

    def chat_stream(messages, **options):
        stream = ollama.chat(
            model=chat_model,
            messages=messages,
            stream=True,
            **options,
        )

        for chunk in stream:
            content = chunk.get("message", {}).get("content", "")
            if content:
                yield content

    def embed(text):
        response = ollama.embed(
            model=embedding_model,
            input=text,
        )
        return response["embeddings"][0]

    for name, description, handler in [
        (
            LLM_CHAT,
            "Generates a complete chat reply from the local "
            "language model.",
            chat,
        ),
        (
            LLM_CHAT_STREAM,
            "Generates a chat reply from the local language "
            "model as a stream of text chunks.",
            chat_stream,
        ),
        (
            LLM_EMBED,
            "Returns an embedding vector for a piece of text.",
            embed,
        ),
    ]:
        registry.register(
            CapabilityDefinition(
                name=name,
                description=description,
                provider=OLLAMA_PROVIDER,
                handler=handler,
                category="llm",
                requires_gpu=True,
            )
        )
