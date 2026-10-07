import pytest

from freya.tools.tool_registry import ToolDefinition, ToolRegistry


def make_tool(name="system.time", handler=None, **overrides):
    return ToolDefinition(
        name=name,
        description="Test tool.",
        handler=handler or (lambda *args, **kwargs: "ok"),
        **overrides,
    )


@pytest.fixture
def registry():
    return ToolRegistry()


def test_register_and_lookup_is_case_insensitive(registry):
    tool = make_tool("System.Time")

    registry.register(tool)

    assert registry.exists(" SYSTEM.TIME ")
    assert registry.get("system.time") is tool
    # Unlike CapabilityRegistry, the stored definition keeps its original name.
    assert tool.name == "System.Time"


@pytest.mark.parametrize("name", ["", "   "])
def test_register_rejects_empty_name(registry, name):
    with pytest.raises(ValueError):
        registry.register(make_tool(name))


def test_register_rejects_duplicate_name(registry):
    first = make_tool()
    registry.register(first)

    with pytest.raises(ValueError):
        registry.register(make_tool(" SYSTEM.TIME "))

    assert registry.get("system.time") is first


def test_lookup_by_alias(registry):
    tool = make_tool(aliases=["Clock", " what time is it ", ""])

    registry.register(tool)

    assert registry.get("clock") is tool
    assert registry.get("WHAT TIME IS IT") is tool
    assert registry.exists("clock")


def test_alias_cannot_shadow_registered_tool(registry):
    registry.register(make_tool("system.time"))

    with pytest.raises(ValueError):
        registry.register(make_tool("system.clock", aliases=["system.time"]))


def test_alias_cannot_be_registered_twice(registry):
    registry.register(make_tool("system.time", aliases=["clock"]))

    with pytest.raises(ValueError):
        registry.register(make_tool("system.clock", aliases=["Clock"]))


def test_get_unknown_returns_none(registry):
    assert registry.get("missing") is None
    assert not registry.exists("missing")


def test_unregister_removes_tool_and_its_aliases(registry):
    registry.register(make_tool("system.time", aliases=["clock", "time"]))
    registry.register(make_tool("system.disk", aliases=["disk"]))

    assert registry.unregister("clock") is True

    assert not registry.exists("system.time")
    assert not registry.exists("clock")
    assert not registry.exists("time")
    assert registry.exists("disk")
    assert registry.unregister("system.time") is False


def test_alias_can_be_reused_after_unregister(registry):
    registry.register(make_tool("system.time", aliases=["clock"]))
    registry.unregister("system.time")
    replacement = make_tool("system.clock", aliases=["clock"])

    registry.register(replacement)

    assert registry.get("clock") is replacement


def test_list_tools_returns_copy(registry):
    registry.register(make_tool("a"))
    registry.register(make_tool("b"))

    listed = registry.list_tools()
    listed.clear()

    assert [tool.name for tool in registry.list_tools()] == ["a", "b"]


def test_execute_passes_arguments_and_returns_result(registry):
    calls = []

    def handler(*args, **kwargs):
        calls.append((args, kwargs))
        return {"time": "12:00"}

    registry.register(make_tool(handler=handler, aliases=["clock"]))

    result = registry.execute("Clock", "utc", fmt="short")

    assert calls == [(("utc",), {"fmt": "short"})]
    assert result.success is True
    assert result.tool_name == "system.time"
    assert result.result == {"time": "12:00"}
    assert result.error is None


def test_execute_unknown_tool(registry):
    result = registry.execute("Missing")

    assert result.success is False
    assert result.tool_name == "Missing"
    assert result.error == "Unknown tool: Missing"


def test_execute_contains_handler_exceptions(registry):
    def handler():
        raise RuntimeError("tool exploded")

    registry.register(make_tool(handler=handler))

    result = registry.execute("system.time")

    assert result.success is False
    assert result.tool_name == "system.time"
    assert result.result is None
    assert result.error == "tool exploded"


def test_describe_tools_is_serializable_snapshot(registry):
    registry.register(
        make_tool(
            category="system",
            requires_gpu=True,
            destructive=True,
            aliases=["clock"],
        )
    )

    described = registry.describe_tools()

    assert described == [
        {
            "name": "system.time",
            "description": "Test tool.",
            "category": "system",
            "requires_gpu": True,
            "destructive": True,
            "aliases": ["clock"],
        }
    ]

    described[0]["aliases"].append("changed")

    assert registry.get("system.time").aliases == ["clock"]
