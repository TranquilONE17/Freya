import pytest

from freya.core.capabilities import (
    CapabilityDefinition,
    CapabilityRegistry,
)
from freya.tools.system_tools import (
    SYSTEM_TOOLS_PROVIDER,
    register_system_tools,
)
from freya.tools.tool_executor import SafeToolExecutor
from freya.tools.tool_router import FreyaToolRouter
from freya.tools.tool_selector import LLMToolSelector, ToolSelection


@pytest.fixture
def registry():
    registry = CapabilityRegistry()
    register_system_tools(registry)
    return registry


def add_capability(registry, name, handler, **overrides):
    registry.register(
        CapabilityDefinition(
            name=name,
            description="Test capability.",
            provider="test-provider",
            handler=handler,
            **overrides,
        )
    )


def test_system_tools_register_as_capabilities(registry):
    described = {c["name"]: c for c in registry.describe_capabilities()}

    assert set(described) == {"system.info", "system.disk", "system.gpu"}
    for capability in described.values():
        assert capability["provider"] == SYSTEM_TOOLS_PROVIDER
        assert capability["category"] == "system"
        assert capability["destructive"] is False


@pytest.mark.parametrize(
    "alias, name",
    [
        ("system", "system.info"),
        ("computer.info", "system.info"),
        ("disk", "system.disk"),
        ("disk.info", "system.disk"),
        ("gpu", "system.gpu"),
        ("gpu.status", "system.gpu"),
    ],
)
def test_system_tool_aliases_resolve(registry, alias, name):
    assert registry.get(alias).name == name


def test_system_tools_cannot_be_registered_twice(registry):
    with pytest.raises(ValueError):
        register_system_tools(registry)


@pytest.mark.parametrize(
    "text, name",
    [
        ("what is my gpu temperature", "system.gpu"),
        ("how much disk space is free", "system.disk"),
    ],
)
def test_router_targets_are_registered_capabilities(registry, text, name):
    request = FreyaToolRouter().route(text)

    assert request is not None
    assert request.tool == name
    assert registry.exists(request.tool)


def test_system_info_executes_through_registry(registry):
    result = registry.execute("system.info")

    assert result.success is True
    assert result.capability_name == "system.info"
    assert result.provider == SYSTEM_TOOLS_PROVIDER
    assert result.result["python_version"]


def test_executor_runs_selected_capability():
    registry = CapabilityRegistry()
    add_capability(registry, "system.time", lambda: "12:00", aliases=["clock"])
    executor = SafeToolExecutor(registry)

    result = executor.execute_selection(
        ToolSelection(use_tool=True, tool="clock", confidence=0.9)
    )

    assert result.executed is True
    assert result.blocked is False
    assert result.tool_name == "system.time"
    assert result.result == "12:00"
    assert result.error is None


def test_executor_blocks_destructive_capability():
    calls = []
    registry = CapabilityRegistry()
    add_capability(
        registry,
        "files.delete",
        lambda: calls.append(1),
        destructive=True,
    )
    executor = SafeToolExecutor(registry)

    result = executor.execute_selection(
        ToolSelection(use_tool=True, tool="files.delete", confidence=1.0)
    )

    assert calls == []
    assert result.executed is False
    assert result.blocked is True
    assert result.tool_name == "files.delete"


def test_executor_blocks_unregistered_and_low_confidence_selections():
    calls = []
    registry = CapabilityRegistry()
    add_capability(registry, "system.time", lambda: calls.append(1))
    executor = SafeToolExecutor(registry)

    unknown = executor.execute_selection(
        ToolSelection(use_tool=True, tool="missing", confidence=1.0)
    )
    unsure = executor.execute_selection(
        ToolSelection(use_tool=True, tool="system.time", confidence=0.5)
    )
    not_needed = executor.execute_selection(
        ToolSelection(use_tool=False, tool=None, confidence=1.0)
    )

    assert calls == []
    assert (unknown.executed, unknown.blocked) == (False, True)
    assert (unsure.executed, unsure.blocked) == (False, True)
    assert (not_needed.requested, not_needed.executed) == (False, False)


def test_executor_reports_handler_failure():
    def handler():
        raise RuntimeError("tool exploded")

    registry = CapabilityRegistry()
    add_capability(registry, "system.time", handler)

    result = SafeToolExecutor(registry).execute_selection(
        ToolSelection(use_tool=True, tool="system.time", confidence=0.9)
    )

    assert result.tool_name == "system.time"
    assert result.result is None
    assert result.error == "tool exploded"


def test_selector_offers_registered_capabilities_and_validates_choice(
    registry, monkeypatch
):
    prompts = []

    def fake_chat(model, messages, **kwargs):
        prompts.append(messages[-1]["content"])
        return {
            "message": {
                "content": (
                    '{"use_tool": true, "tool": "GPU", '
                    '"confidence": 0.9, "reason": "needs live data"}'
                )
            }
        }

    monkeypatch.setattr("freya.tools.tool_selector.ollama.chat", fake_chat)

    selection = LLMToolSelector(registry).select("How hot is my GPU?")

    assert '"name": "system.gpu"' in prompts[0]
    assert selection.use_tool is True
    # An alias chosen by the model is resolved to the canonical name.
    assert selection.tool == "system.gpu"


def test_selector_rejects_unregistered_choice(registry, monkeypatch):
    monkeypatch.setattr(
        "freya.tools.tool_selector.ollama.chat",
        lambda **kwargs: {
            "message": {
                "content": (
                    '{"use_tool": true, "tool": "files.delete", '
                    '"confidence": 1.0, "reason": "x"}'
                )
            }
        },
    )

    selection = LLMToolSelector(registry).select("Delete everything")

    assert selection.use_tool is False
    assert selection.tool is None
