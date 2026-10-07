import json
import urllib.error

import pytest

from freya.core.capabilities import CapabilityRegistry
from freya.tools import sensors
from freya.tools.system_tools import register_system_tools


def sensor(text, value, kind, sensor_id):
    return {
        "Text": text,
        "Value": value,
        "Type": kind,
        "SensorId": sensor_id,
        "Children": [],
    }


def group(text, *children):
    return {"Text": text, "Children": list(children)}


def hardware(text, hardware_id, *children):
    return {"Text": text, "HardwareId": hardware_id, "Children": list(children)}


TREE = group(
    "Sensor",
    group(
        "TESTPC",
        hardware(
            "Test Board",
            "/motherboard",
            hardware(
                "Monitor Chip",
                "/lpc/chip/0",
                group(
                    "Temperatures",
                    sensor("CPU Core", "48,5 °C", "Temperature", "/lpc/t/0"),
                    sensor("Temperature #1", "39.5 °C", "Temperature", "/lpc/t/1"),
                ),
                group(
                    "Fans",
                    sensor("Fan #1", "0 RPM", "Fan", "/lpc/f/0"),
                    sensor("Fan #2", "1479 RPM", "Fan", "/lpc/f/1"),
                ),
                group(
                    "Voltages",
                    sensor("Vcore", "1.250 V", "Voltage", "/lpc/v/0"),
                ),
            ),
        ),
        hardware(
            "Test CPU",
            "/intelcpu/0",
            group(
                "Temperatures",
                sensor("Core Max", "42.0 °C", "Temperature", "/cpu/t/0"),
                sensor("CPU Package", "41.0 °C", "Temperature", "/cpu/t/1"),
                sensor("P-Core #1", "36.0 °C", "Temperature", "/cpu/t/2"),
                sensor("E-Core #12", "38.0 °C", "Temperature", "/cpu/t/3"),
                sensor(
                    "P-Core #1 Distance to TjMax", "64.0 °C", "Temperature", "/cpu/t/4"
                ),
            ),
            group(
                "Powers",
                sensor("CPU Package", "89.4 W", "Power", "/cpu/p/0"),
                sensor("CPU Platform", "0.0 W", "Power", "/cpu/p/1"),
            ),
            group("Load", sensor("CPU Total", "5.0 %", "Load", "/cpu/l/0")),
        ),
        hardware(
            "Test SSD",
            "/nvme/0",
            group(
                "Temperatures",
                sensor("Composite Temperature", "51.0 °C", "Temperature", "/ssd/t/0"),
                sensor("Warning Temperature", "69.0 °C", "Temperature", "/ssd/t/1"),
                sensor("Critical Temperature", "74.0 °C", "Temperature", "/ssd/t/2"),
            ),
            group(
                "Levels",
                sensor("Available Spare", "100.0 %", "Level", "/ssd/v/0"),
                sensor("Percentage Used", "255.0 %", "Level", "/ssd/v/1"),
            ),
        ),
        hardware(
            "Test NIC",
            "/nic/0",
            group("Load", sensor("Utilization", "1.0 %", "Load", "/nic/l/0")),
        ),
    ),
)


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def serve(monkeypatch):
    """Make the sensor service return a given payload."""
    requests = []

    def install(payload):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

        def urlopen(url, timeout=None):
            requests.append((url, timeout))
            return FakeResponse(body)

        monkeypatch.setattr(sensors.urllib.request, "urlopen", urlopen)
        return requests

    return install


def test_readings_are_grouped_and_trimmed(serve):
    requests = serve(TREE)

    readings = sensors.get_sensor_readings()

    assert requests == [("http://127.0.0.1:8085/data.json", 3)]
    assert readings["source"] == "LibreHardwareMonitor"
    assert "not labelled" in readings["note"]
    assert readings["components"] == [
        {
            # A monitoring chip is reported under its board, and a decimal
            # comma is understood.
            "name": "Test Board (Monitor Chip)",
            "temperatures_c": {"CPU Core": 48.5, "Temperature #1": 39.5},
            "fans_rpm": {"Fan #2": 1479},
            "fans_stopped_or_not_connected": 1,
        },
        {
            # Per-core readings, TjMax distances, zero power, and load are
            # left out.
            "name": "Test CPU",
            "temperatures_c": {"Core Max": 42.0, "CPU Package": 41.0},
            "power_w": {"CPU Package": 89.4},
        },
        {
            # Thresholds are separated from readings, and an out-of-range
            # level is dropped.
            "name": "Test SSD",
            "temperatures_c": {"Composite Temperature": 51.0},
            "temperature_limits_c": {
                "Warning Temperature": 69.0,
                "Critical Temperature": 74.0,
            },
            "levels_percent": {"Available Spare": 100.0},
        },
        # The network adapter has nothing relevant, so it is omitted.
    ]
    json.dumps(readings)


def test_unreachable_service_gives_a_helpful_error(monkeypatch):
    def refuse(url, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(sensors.urllib.request, "urlopen", refuse)

    with pytest.raises(RuntimeError) as error:
        sensors.get_sensor_readings()

    assert "LibreHardwareMonitor must be running" in str(error.value)


@pytest.mark.parametrize(
    "payload, message",
    [
        (b"<html>not json</html>", "could not be read"),
        (group("Sensor"), "no readings"),
        (b"x" * (sensors.MAX_RESPONSE_BYTES + 10), "too much data"),
    ],
    ids=["not-json", "no-sensors", "oversized"],
)
def test_bad_responses_are_rejected(serve, payload, message):
    serve(payload)

    with pytest.raises(RuntimeError) as error:
        sensors.get_sensor_readings()

    assert message in str(error.value)


def test_sensor_tool_reports_failure_through_the_registry(monkeypatch):
    def refuse(url, timeout=None):
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(sensors.urllib.request, "urlopen", refuse)
    registry = CapabilityRegistry()
    register_system_tools(registry)

    result = registry.execute("temperatures")

    assert result.success is False
    assert result.capability_name == "system.sensors"
    assert "LibreHardwareMonitor" in result.error
    assert registry.get("system.sensors").optional_dependencies == [
        "LibreHardwareMonitor web server"
    ]
