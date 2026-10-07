import json
import re
import urllib.error
import urllib.request

from freya.config import SENSOR_URL


# The sensor service is asked on every call; it is local and answers in
# milliseconds, and readings go stale quickly.
REQUEST_TIMEOUT_SECONDS = 3
MAX_RESPONSE_BYTES = 4 * 1024 * 1024

UNAVAILABLE_MESSAGE = (
    "Sensor readings are not available. LibreHardwareMonitor must be "
    "running as administrator with Options > Remote Web Server > Run "
    "turned on."
)

UNLABELLED_NOTE = (
    "Motherboard sensors named 'Temperature #n' or 'Fan #n' are not "
    "labelled by the board, and a temperature channel with nothing "
    "connected can show a meaningless value."
)

# Per-core readings and fixed thresholds would bury the useful values.
SKIPPED_TEMPERATURES = re.compile(
    r"Distance to TjMax"
    r"|^(?:[PE]-)?Core #\d+$"
    r"|Resolution"
    r"|Low Limit",
    re.IGNORECASE,
)

TEMPERATURE_LIMITS = re.compile(
    r"High Limit|Warning Temperature|Critical Temperature",
    re.IGNORECASE,
)

NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


def _number(text):
    match = NUMBER.search(text or "")

    if match is None:
        return None

    return float(match.group(0).replace(",", "."))


def _fetch(url):
    try:
        with urllib.request.urlopen(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except (urllib.error.URLError, OSError) as exc:
        raise RuntimeError(UNAVAILABLE_MESSAGE) from exc

    if len(body) > MAX_RESPONSE_BYTES:
        raise RuntimeError(
            "The sensor service returned too much data."
        )

    try:
        return json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise RuntimeError(
            "The sensor service returned data that could not be read."
        ) from exc


def _sensors(node):
    """
    Yield every sensor reading beneath a node.
    """
    for child in node.get("Children") or []:
        if child.get("Type") and child.get("SensorId"):
            yield child
        else:
            yield from _sensors(child)


def _is_hardware(node):
    return bool(node.get("HardwareId"))


def _hardware(node, parent_name=None):
    """
    Yield (name, node) for each hardware device. A chip nested inside
    another device, such as a motherboard's monitoring chip, is
    reported under its parent's name.
    """
    for child in node.get("Children") or []:
        if not _is_hardware(child):
            yield from _hardware(child, parent_name)
            continue

        name = (child.get("Text") or "").strip()

        if parent_name:
            name = f"{parent_name} ({name})"

        yield name, child
        yield from _hardware(child, name)


def _own_sensors(node):
    """
    Sensors that belong to this device rather than to a nested one.
    """
    for child in node.get("Children") or []:
        if _is_hardware(child):
            continue

        if child.get("Type") and child.get("SensorId"):
            yield child
        else:
            yield from _own_sensors(child)


def _summarize(name, node):
    component = {"name": name}

    temperatures = {}
    limits = {}
    fans = {}
    stopped_fans = 0
    power = {}
    levels = {}

    for sensor in _own_sensors(node):
        label = (sensor.get("Text") or "").strip()
        value = _number(sensor.get("Value"))
        kind = sensor.get("Type")

        if value is None or not label:
            continue

        if kind == "Temperature":
            if TEMPERATURE_LIMITS.search(label):
                limits[label] = value
            elif not SKIPPED_TEMPERATURES.search(label):
                temperatures[label] = value
        elif kind == "Fan":
            if value > 0:
                fans[label] = round(value)
            else:
                stopped_fans += 1
        elif kind == "Power":
            if value > 0:
                power[label] = value
        elif kind == "Level":
            # Some drives report filler values outside 0-100.
            if 0 <= value <= 100:
                levels[label] = value

    if temperatures:
        component["temperatures_c"] = temperatures
    if limits:
        component["temperature_limits_c"] = limits
    if fans:
        component["fans_rpm"] = fans
    if stopped_fans:
        component["fans_stopped_or_not_connected"] = stopped_fans
    if power:
        component["power_w"] = power
    if levels:
        component["levels_percent"] = levels

    return component if len(component) > 1 else None


def get_sensor_readings(url=None):
    """
    Return current temperatures, fan speeds, power draw, and drive
    wear levels for each component, read from LibreHardwareMonitor's
    local web server.

    This is read-only.
    """
    data = _fetch(url or SENSOR_URL)

    components = [
        component
        for component in (
            _summarize(name, node)
            for name, node in _hardware(data)
        )
        if component is not None
    ]

    if not components:
        raise RuntimeError(
            "The sensor service reported no readings. "
            "LibreHardwareMonitor may need to run as administrator."
        )

    return {
        "source": "LibreHardwareMonitor",
        "components": components,
        "note": UNLABELLED_NOTE,
    }
