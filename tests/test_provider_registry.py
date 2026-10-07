import pytest

from freya.core.providers import (
    ProviderDefinition,
    ProviderHealth,
    ProviderRegistry,
    ProviderState,
)


def make_provider(provider_id="ollama-local", **overrides):
    return ProviderDefinition(
        provider_id=provider_id,
        name="Test provider",
        **overrides,
    )


def failing():
    raise RuntimeError("handler exploded")


@pytest.fixture
def registry():
    return ProviderRegistry()


def test_register_normalizes_id_and_capabilities(registry):
    provider = make_provider(
        "  Ollama-Local ",
        capabilities=[" LLM.Chat ", "LLM.EMBED"],
    )

    registry.register(provider)

    assert provider.provider_id == "ollama-local"
    assert provider.capabilities == ["llm.chat", "llm.embed"]
    assert registry.exists(" OLLAMA-LOCAL ")
    assert registry.get("Ollama-Local") is provider


@pytest.mark.parametrize("provider_id", ["", "   "])
def test_register_rejects_empty_id(registry, provider_id):
    with pytest.raises(ValueError):
        registry.register(make_provider(provider_id))


def test_register_replaces_existing_provider(registry):
    first = make_provider()
    second = make_provider()

    registry.register(first)
    registry.register(second)

    assert registry.get("ollama-local") is second
    assert registry.list_providers() == [second]


def test_new_provider_defaults(registry):
    registry.register(make_provider())
    provider = registry.get("ollama-local")

    assert provider.node_id == "local"
    assert provider.health == ProviderHealth.UNKNOWN
    assert provider.state == ProviderState.STOPPED


def test_get_unknown_returns_none(registry):
    assert registry.get("missing") is None
    assert not registry.exists("missing")


def test_unregister(registry):
    registry.register(make_provider())

    assert registry.unregister(" OLLAMA-LOCAL ") is True
    assert not registry.exists("ollama-local")
    assert registry.unregister("ollama-local") is False


def test_providers_for_capability(registry):
    ollama = make_provider("ollama-local", capabilities=["llm.chat", "llm.embed"])
    remote = make_provider("ollama-rack", capabilities=["llm.chat"])
    whisper = make_provider("whisper-local", capabilities=["speech.transcribe"])
    for provider in (ollama, remote, whisper):
        registry.register(provider)

    assert registry.providers_for_capability(" LLM.Chat ") == [ollama, remote]
    assert registry.providers_for_capability("speech.transcribe") == [whisper]
    assert registry.providers_for_capability("image.generate") == []


def test_set_health_and_state(registry):
    registry.register(make_provider())

    assert registry.set_health("ollama-local", ProviderHealth.DEGRADED) is True
    assert registry.set_state("ollama-local", ProviderState.RUNNING) is True

    provider = registry.get("ollama-local")
    assert provider.health == ProviderHealth.DEGRADED
    assert provider.state == ProviderState.RUNNING


def test_set_health_and_state_unknown_return_false(registry):
    assert registry.set_health("missing", ProviderHealth.HEALTHY) is False
    assert registry.set_state("missing", ProviderState.RUNNING) is False


def test_is_usable_requires_running_and_healthy(registry):
    registry.register(make_provider())

    for state in ProviderState:
        for health in ProviderHealth:
            registry.set_state("ollama-local", state)
            registry.set_health("ollama-local", health)

            expected = (
                state == ProviderState.RUNNING
                and health == ProviderHealth.HEALTHY
            )
            assert registry.is_usable("ollama-local") is expected


def test_is_usable_false_for_unknown(registry):
    assert registry.is_usable("missing") is False


def test_start_success(registry):
    seen_states = []
    provider = make_provider()
    provider.start_handler = lambda: seen_states.append(provider.state) or "started"
    registry.register(provider)

    result = registry.start(" OLLAMA-LOCAL ")

    assert seen_states == [ProviderState.STARTING]
    assert result.success is True
    assert result.provider_id == "ollama-local"
    assert result.operation == "start"
    assert result.result == "started"
    assert provider.state == ProviderState.RUNNING
    # Starting does not by itself make a provider healthy.
    assert provider.health == ProviderHealth.UNKNOWN
    assert registry.is_usable("ollama-local") is False


def test_start_failure_is_contained(registry):
    registry.register(make_provider(start_handler=failing))

    result = registry.start("ollama-local")

    provider = registry.get("ollama-local")
    assert result.success is False
    assert result.operation == "start"
    assert result.error == "handler exploded"
    assert provider.state == ProviderState.FAILED
    assert provider.health == ProviderHealth.UNHEALTHY


def test_start_unknown_provider(registry):
    result = registry.start(" Missing ")

    assert result.success is False
    assert result.provider_id == "missing"
    assert result.error == "Provider is not registered."


def test_start_disabled_provider_does_not_call_handler(registry):
    calls = []
    registry.register(
        make_provider(
            state=ProviderState.DISABLED,
            start_handler=lambda: calls.append(1),
        )
    )

    result = registry.start("ollama-local")

    assert calls == []
    assert result.success is False
    assert result.error == "Provider is disabled."
    assert registry.get("ollama-local").state == ProviderState.DISABLED


def test_start_without_handler_leaves_state_unchanged(registry):
    registry.register(make_provider())

    result = registry.start("ollama-local")

    assert result.success is False
    assert "start handler" in result.error
    assert registry.get("ollama-local").state == ProviderState.STOPPED


def test_stop_success(registry):
    seen_states = []
    provider = make_provider(state=ProviderState.RUNNING)
    provider.stop_handler = lambda: seen_states.append(provider.state) or "stopped"
    registry.register(provider)

    result = registry.stop("ollama-local")

    assert seen_states == [ProviderState.STOPPING]
    assert result.success is True
    assert result.operation == "stop"
    assert result.result == "stopped"
    assert provider.state == ProviderState.STOPPED


def test_stop_failure_is_contained(registry):
    registry.register(
        make_provider(state=ProviderState.RUNNING, stop_handler=failing)
    )

    result = registry.stop("ollama-local")

    provider = registry.get("ollama-local")
    assert result.success is False
    assert result.error == "handler exploded"
    assert provider.state == ProviderState.FAILED
    assert provider.health == ProviderHealth.UNHEALTHY


def test_stop_unknown_provider(registry):
    result = registry.stop("missing")

    assert result.success is False
    assert result.operation == "stop"
    assert result.error == "Provider is not registered."


def test_stop_without_handler_leaves_state_unchanged(registry):
    registry.register(make_provider(state=ProviderState.RUNNING))

    result = registry.stop("ollama-local")

    assert result.success is False
    assert "stop handler" in result.error
    assert registry.get("ollama-local").state == ProviderState.RUNNING


@pytest.mark.parametrize(
    "reported, expected",
    [
        (True, ProviderHealth.HEALTHY),
        (False, ProviderHealth.UNHEALTHY),
        (ProviderHealth.DEGRADED, ProviderHealth.DEGRADED),
        (ProviderHealth.OFFLINE, ProviderHealth.OFFLINE),
        (None, ProviderHealth.UNKNOWN),
        ("fine", ProviderHealth.UNKNOWN),
        (1, ProviderHealth.UNKNOWN),
    ],
)
def test_check_health_maps_handler_result(registry, reported, expected):
    registry.register(
        make_provider(
            health=ProviderHealth.HEALTHY,
            health_handler=lambda: reported,
        )
    )

    result = registry.check_health("ollama-local")

    assert result.success is True
    assert result.operation == "health"
    assert result.result == expected
    assert registry.get("ollama-local").health == expected


def test_check_health_failure_marks_unhealthy(registry):
    registry.register(
        make_provider(
            health=ProviderHealth.HEALTHY,
            state=ProviderState.RUNNING,
            health_handler=failing,
        )
    )

    result = registry.check_health("ollama-local")

    provider = registry.get("ollama-local")
    assert result.success is False
    assert result.error == "handler exploded"
    assert provider.health == ProviderHealth.UNHEALTHY
    # A failed health check does not change the lifecycle state.
    assert provider.state == ProviderState.RUNNING
    assert registry.is_usable("ollama-local") is False


def test_check_health_unknown_provider(registry):
    result = registry.check_health("missing")

    assert result.success is False
    assert result.operation == "health"
    assert result.error == "Provider is not registered."


def test_check_health_without_handler_leaves_health_unchanged(registry):
    registry.register(make_provider(health=ProviderHealth.HEALTHY))

    result = registry.check_health("ollama-local")

    assert result.success is False
    assert "health handler" in result.error
    assert registry.get("ollama-local").health == ProviderHealth.HEALTHY


def test_describe_providers_is_serializable_snapshot(registry):
    registry.register(
        make_provider(
            node_id="workstation",
            capabilities=["llm.chat"],
            health=ProviderHealth.HEALTHY,
            state=ProviderState.RUNNING,
            start_handler=lambda: None,
            metadata={"url": "http://127.0.0.1:11434"},
        )
    )

    described = registry.describe_providers()

    assert described == [
        {
            "provider_id": "ollama-local",
            "name": "Test provider",
            "node_id": "workstation",
            "capabilities": ["llm.chat"],
            "health": "healthy",
            "state": "running",
            "metadata": {"url": "http://127.0.0.1:11434"},
        }
    ]

    described[0]["capabilities"].append("changed")
    described[0]["metadata"]["url"] = "changed"
    provider = registry.get("ollama-local")

    assert provider.capabilities == ["llm.chat"]
    assert provider.metadata == {"url": "http://127.0.0.1:11434"}
