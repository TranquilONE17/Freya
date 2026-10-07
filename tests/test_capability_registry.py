import pytest

from freya.core.capabilities import (
    CapabilityDefinition,
    CapabilityRegistry,
    CapabilityStatus,
)


def make_capability(name="llm.chat", handler=None, **overrides):
    return CapabilityDefinition(
        name=name,
        description="Test capability.",
        provider="test-provider",
        handler=handler or (lambda *args, **kwargs: "ok"),
        **overrides,
    )


@pytest.fixture
def registry():
    return CapabilityRegistry()


def test_register_normalizes_name(registry):
    capability = make_capability("  LLM.Chat ")

    registry.register(capability)

    assert capability.name == "llm.chat"
    assert registry.exists("llm.chat")
    assert registry.exists(" LLM.CHAT ")
    assert registry.get("Llm.Chat") is capability


@pytest.mark.parametrize("name", ["", "   "])
def test_register_rejects_empty_name(registry, name):
    with pytest.raises(ValueError):
        registry.register(make_capability(name))


def test_register_replaces_existing_capability(registry):
    first = make_capability()
    second = make_capability()

    registry.register(first)
    registry.register(second)

    assert registry.get("llm.chat") is second
    assert registry.list_capabilities() == [second]


def test_get_unknown_returns_none(registry):
    assert registry.get("missing") is None
    assert not registry.exists("missing")


def test_unregister(registry):
    registry.register(make_capability())

    assert registry.unregister(" LLM.CHAT ") is True
    assert not registry.exists("llm.chat")
    assert registry.unregister("llm.chat") is False


def test_list_capabilities_returns_copy(registry):
    registry.register(make_capability("a"))
    registry.register(make_capability("b"))

    listed = registry.list_capabilities()
    listed.clear()

    assert [c.name for c in registry.list_capabilities()] == ["a", "b"]


def test_new_capability_is_available_by_default(registry):
    registry.register(make_capability())

    assert registry.is_available("llm.chat")


def test_is_available_false_for_unknown(registry):
    assert registry.is_available("missing") is False


@pytest.mark.parametrize(
    "status",
    [
        CapabilityStatus.DEGRADED,
        CapabilityStatus.UNAVAILABLE,
        CapabilityStatus.DISABLED,
    ],
)
def test_only_available_status_counts_as_available(registry, status):
    registry.register(make_capability())

    assert registry.set_status("llm.chat", status) is True
    assert registry.get("llm.chat").status == status
    assert registry.is_available("llm.chat") is False


def test_set_status_unknown_returns_false(registry):
    assert registry.set_status("missing", CapabilityStatus.DISABLED) is False


def test_execute_passes_arguments_and_returns_result(registry):
    calls = []

    def handler(*args, **kwargs):
        calls.append((args, kwargs))
        return {"answer": 42}

    registry.register(make_capability(handler=handler))

    result = registry.execute(" LLM.Chat ", "hello", temperature=0)

    assert calls == [(("hello",), {"temperature": 0})]
    assert result.success is True
    assert result.capability_name == "llm.chat"
    assert result.provider == "test-provider"
    assert result.result == {"answer": 42}
    assert result.error is None


def test_execute_unknown_capability(registry):
    result = registry.execute(" Missing ")

    assert result.success is False
    assert result.capability_name == "missing"
    assert result.provider is None
    assert result.error == "Capability is not registered."


@pytest.mark.parametrize(
    "status",
    [
        CapabilityStatus.DEGRADED,
        CapabilityStatus.UNAVAILABLE,
        CapabilityStatus.DISABLED,
    ],
)
def test_execute_does_not_call_handler_unless_available(registry, status):
    calls = []
    registry.register(
        make_capability(handler=lambda: calls.append(1), status=status)
    )

    result = registry.execute("llm.chat")

    assert calls == []
    assert result.success is False
    assert result.provider == "test-provider"
    assert status.value in result.error


def test_execute_contains_handler_exceptions(registry):
    def handler():
        raise RuntimeError("provider exploded")

    registry.register(make_capability(handler=handler))

    result = registry.execute("llm.chat")

    assert result.success is False
    assert result.capability_name == "llm.chat"
    assert result.provider == "test-provider"
    assert result.result is None
    assert result.error == "provider exploded"


def test_describe_capabilities_is_serializable_snapshot(registry):
    registry.register(
        make_capability(
            category="llm",
            status=CapabilityStatus.DEGRADED,
            optional_dependencies=["gpu"],
            metadata={"model": "test"},
        )
    )

    described = registry.describe_capabilities()

    assert described == [
        {
            "name": "llm.chat",
            "description": "Test capability.",
            "provider": "test-provider",
            "category": "llm",
            "status": "degraded",
            "optional_dependencies": ["gpu"],
            "metadata": {"model": "test"},
        }
    ]

    described[0]["optional_dependencies"].append("changed")
    described[0]["metadata"]["model"] = "changed"
    capability = registry.get("llm.chat")

    assert capability.optional_dependencies == ["gpu"]
    assert capability.metadata == {"model": "test"}
