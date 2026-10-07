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

    assert set(described) == {
        "system.info",
        "system.disk",
        "system.gpu",
        "system.cpu",
        "system.memory",
        "system.hardware",
    }
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
        ("drives", "system.disk"),
        ("cpu", "system.cpu"),
        ("ram", "system.memory"),
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
        ("how much vram is in use", "system.gpu"),
        ("how much memory is my gpu using", "system.gpu"),
        ("how much disk space is free", "system.disk"),
        ("what drives do I have", "system.disk"),
        ("list my drives", "system.disk"),
        ("show me drive info", "system.disk"),
        ("how full is my D drive", "system.disk"),
        ("what's my cpu usage", "system.cpu"),
        ("how busy is the processor", "system.cpu"),
        ("what cpu do I have", "system.cpu"),
        ("how many cores do I have", "system.cpu"),
        ("how much ram am I using", "system.memory"),
        ("how much RAM do I have", "system.memory"),
        ("what's my memory usage", "system.memory"),
        ("how much memory is free", "system.memory"),
        ("is there any system memory available", "system.memory"),
        ("list my hardware", "system.hardware"),
        ("what hardware do I have", "system.hardware"),
        ("show me the components in my pc", "system.hardware"),
        ("what are my computer specs", "system.hardware"),
        ("what motherboard do I have", "system.hardware"),
        ("what's inside this computer", "system.hardware"),
        ("tell me about my ram sticks", "system.hardware"),
        ("which network adapters are installed", "system.hardware"),
        ("what version of windows am I on", "system.info"),
    ],
)
def test_router_targets_are_registered_capabilities(registry, text, name):
    request = FreyaToolRouter().route(text)

    assert request is not None
    assert request.tool == name
    assert registry.exists(request.tool)


@pytest.mark.parametrize(
    "text",
    [
        "what do you remember about me",
        "do you have a good memory",
        "remember that my favorite color is green",
        "what is RAM",
        "tell me a joke about a processor",
        "I went for a drive yesterday",
        "tell me a joke",
        "what are the components of a good essay",
        "list the parts of a cell in detail",
        "what hardware store is closest",
    ],
)
def test_router_leaves_conversation_alone(text):
    assert FreyaToolRouter().route(text) is None


def test_cpu_memory_and_disk_tools_return_live_data(registry):
    cpu = registry.execute("system.cpu").result
    memory = registry.execute("system.memory").result
    drives = registry.execute("system.disk").result

    assert 0 <= cpu["utilization_percent"] <= 100
    assert cpu["logical_cores"] >= cpu["physical_cores"] >= 1

    assert memory["total_gb"] > 0
    assert 0 < memory["used_percent"] <= 100
    assert memory["used_gb"] + memory["available_gb"] == pytest.approx(
        memory["total_gb"], abs=0.02
    )

    assert len(drives) >= 1
    for drive in drives:
        assert drive["filesystem"]
        assert drive["total_gb"] > 0
        assert 0 <= drive["used_percent"] <= 100


def test_hardware_inventory_parsing_and_formatting(monkeypatch):
    import json
    from types import SimpleNamespace

    from freya.tools import hardware_inventory

    raw = {
        "os": {"Caption": "Test OS ", "OSArchitecture": "64-bit", "BuildNumber": "1"},
        "system": {"Manufacturer": "Acme", "Model": "Box"},
        "motherboard": {"Manufacturer": "Acme", "Product": "Board 1"},
        "bios": {"Manufacturer": "Acme", "SMBIOSBIOSVersion": "1.2"},
        "processors": {
            "Name": "Test CPU",
            "NumberOfCores": 8,
            "NumberOfLogicalProcessors": 16,
        },
        "memory_modules": [
            {"Capacity": 17179869184, "ConfiguredClockSpeed": 4800,
             "Manufacturer": "Acme", "PartNumber": "RAM-1 ", "DeviceLocator": "DIMM1"},
            {"Capacity": 17179869184, "Speed": 4800,
             "Manufacturer": "Acme", "PartNumber": "RAM-1", "DeviceLocator": "DIMM2"},
        ],
        "disks": {"FriendlyName": "Test SSD", "MediaType": "SSD",
                  "BusType": "NVMe", "Size": 1073741824000, "HealthStatus": "Healthy"},
        "graphics": {"Name": "Test GPU", "DriverVersion": "1.0",
                     "CurrentHorizontalResolution": 1920,
                     "CurrentVerticalResolution": 1080, "CurrentRefreshRate": 60},
        "network_adapters": [
            {"Name": "Wired", "NetEnabled": True, "Speed": 1000000000},
            {"Name": "Wireless", "NetEnabled": False, "Speed": 9223372036854775807},
        ],
        "sound_devices": None,
    }

    monkeypatch.setattr(hardware_inventory.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        hardware_inventory.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps(raw)),
    )

    inventory = hardware_inventory.get_hardware_inventory()
    lines = hardware_inventory.format_hardware_inventory(inventory)

    # A single object from PowerShell becomes a one-row list.
    assert inventory["disks"][0]["FriendlyName"] == "Test SSD"
    assert inventory["os"][0]["Caption"] == "Test OS"
    assert inventory["sound_devices"] == []

    assert "Motherboard: Acme Board 1" in lines
    assert "Processor: Test CPU — 8 cores / 16 threads" in lines
    assert "Memory: 32.0 GB in 2 module(s)" in lines
    assert "  DIMM1: 16.0 GB 4800 MHz Acme RAM-1" in lines
    assert "Disk: Test SSD — 1000.0 GB SSD NVMe (health: Healthy)" in lines
    assert (
        "Graphics: Test GPU (driver 1.0) driving 1920x1080 at 60 Hz" in lines
    )
    assert "Network: Wired — connected at 1000 Mbps" in lines
    assert "Network: Wireless — not connected" in lines


def test_hardware_inventory_is_windows_only(monkeypatch):
    from freya.tools import hardware_inventory

    monkeypatch.setattr(hardware_inventory.platform, "system", lambda: "Linux")

    with pytest.raises(RuntimeError):
        hardware_inventory.get_hardware_inventory()


def test_unreadable_drives_are_skipped(monkeypatch):
    from collections import namedtuple

    from freya.tools import system_tools

    Partition = namedtuple("Partition", "device mountpoint fstype opts")
    Usage = namedtuple("Usage", "total used free")

    monkeypatch.setattr(
        system_tools.psutil,
        "disk_partitions",
        lambda all=False: [
            Partition("C:\\", "C:\\", "NTFS", "rw,fixed"),
            Partition("E:\\", "E:\\", "", "cdrom"),
            Partition("F:\\", "F:\\", "exFAT", "rw,removable"),
            Partition("G:\\", "G:\\", "NTFS", "rw,fixed"),
        ],
    )

    def usage(path):
        if path == "G:\\":
            raise PermissionError("The device is not ready.")
        return Usage(100 * 1024**3, 25 * 1024**3, 75 * 1024**3)

    monkeypatch.setattr(system_tools.shutil, "disk_usage", usage)

    drives = system_tools.get_disk_info()

    assert [d["drive"] for d in drives] == ["C:\\", "F:\\"]
    assert [d["removable"] for d in drives] == [False, True]
    assert drives[0]["used_percent"] == 25.0
    assert drives[0]["free_gb"] == 75.0


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
