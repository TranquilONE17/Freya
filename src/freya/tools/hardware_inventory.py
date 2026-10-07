import json
import platform
import subprocess


# Read-only CIM queries. Serial numbers, MAC addresses, and other unique
# identifiers are deliberately not collected.
INVENTORY_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'

function Rows($items, $names) {
    @($items | Select-Object -Property $names)
}

$physicalDisks = Rows (Get-PhysicalDisk) @(
    'FriendlyName', 'MediaType', 'BusType', 'Size', 'HealthStatus'
)

if ($physicalDisks.Count -eq 0) {
    $physicalDisks = @(
        Get-CimInstance Win32_DiskDrive | ForEach-Object {
            [pscustomobject]@{
                FriendlyName = $_.Model
                MediaType    = $_.MediaType
                BusType      = $_.InterfaceType
                Size         = $_.Size
                HealthStatus = $_.Status
            }
        }
    )
}

[pscustomobject]@{
    os = Rows (Get-CimInstance Win32_OperatingSystem) @(
        'Caption', 'Version', 'BuildNumber', 'OSArchitecture'
    )
    system = Rows (Get-CimInstance Win32_ComputerSystem) @(
        'Manufacturer', 'Model', 'TotalPhysicalMemory'
    )
    motherboard = Rows (Get-CimInstance Win32_BaseBoard) @(
        'Manufacturer', 'Product', 'Version'
    )
    bios = Rows (Get-CimInstance Win32_BIOS) @(
        'Manufacturer', 'SMBIOSBIOSVersion'
    )
    processors = Rows (Get-CimInstance Win32_Processor) @(
        'Name', 'NumberOfCores', 'NumberOfLogicalProcessors',
        'MaxClockSpeed', 'SocketDesignation'
    )
    memory_modules = Rows (Get-CimInstance Win32_PhysicalMemory) @(
        'Manufacturer', 'PartNumber', 'Capacity', 'Speed',
        'ConfiguredClockSpeed', 'DeviceLocator'
    )
    disks = $physicalDisks
    graphics = Rows (Get-CimInstance Win32_VideoController) @(
        'Name', 'DriverVersion', 'CurrentHorizontalResolution',
        'CurrentVerticalResolution', 'CurrentRefreshRate'
    )
    network_adapters = Rows (
        Get-CimInstance Win32_NetworkAdapter |
            Where-Object { $_.PhysicalAdapter }
    ) @('Name', 'NetEnabled', 'Speed')
    sound_devices = Rows (Get-CimInstance Win32_SoundDevice) @(
        'Name', 'Manufacturer'
    )
} | ConvertTo-Json -Depth 4 -Compress
"""

SECTIONS = (
    "os",
    "system",
    "motherboard",
    "bios",
    "processors",
    "memory_modules",
    "disks",
    "graphics",
    "network_adapters",
    "sound_devices",
)


def _clean(value):
    if isinstance(value, str):
        return value.strip()
    return value


def _rows(value):
    """
    PowerShell serializes a one-element list as a bare object.
    """
    if value is None:
        return []

    if isinstance(value, dict):
        value = [value]

    return [
        {key: _clean(item) for key, item in row.items()}
        for row in value
    ]


def get_hardware_inventory():
    """
    Return an inventory of the computer's components.

    This is read-only and Windows-only for now.
    """

    if platform.system() != "Windows":
        raise RuntimeError(
            "Hardware inventory is only supported on Windows."
        )

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            INVENTORY_SCRIPT,
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )

    output = completed.stdout.strip()

    if not output:
        raise RuntimeError(
            "The hardware query returned no data."
        )

    raw = json.loads(output)

    return {
        section: _rows(raw.get(section))
        for section in SECTIONS
    }


def _gb(value):
    if not value:
        return None
    return round(int(value) / 1024**3, 1)


def _join(*parts):
    return " ".join(str(part) for part in parts if part)


def format_hardware_inventory(inventory):
    """
    Turn an inventory into short display lines, one component per line.
    """

    lines = []

    def add(label, text):
        if text:
            lines.append(f"{label}: {text}")

    for row in inventory["os"]:
        add(
            "Operating system",
            _join(
                row.get("Caption"),
                row.get("OSArchitecture"),
                f"(build {row.get('BuildNumber')})",
            ),
        )

    for row in inventory["system"]:
        add(
            "System",
            _join(row.get("Manufacturer"), row.get("Model")),
        )

    for row in inventory["motherboard"]:
        add(
            "Motherboard",
            _join(row.get("Manufacturer"), row.get("Product")),
        )

    for row in inventory["bios"]:
        add(
            "BIOS",
            _join(
                row.get("Manufacturer"),
                row.get("SMBIOSBIOSVersion"),
            ),
        )

    for row in inventory["processors"]:
        add(
            "Processor",
            f"{row.get('Name')} — "
            f"{row.get('NumberOfCores')} cores / "
            f"{row.get('NumberOfLogicalProcessors')} threads",
        )

    modules = inventory["memory_modules"]

    if modules:
        total = sum(
            int(row.get("Capacity") or 0) for row in modules
        )
        add(
            "Memory",
            f"{_gb(total)} GB in {len(modules)} module(s)",
        )

    for row in modules:
        speed = row.get("ConfiguredClockSpeed") or row.get("Speed")
        add(
            f"  {row.get('DeviceLocator') or 'Module'}",
            _join(
                f"{_gb(row.get('Capacity'))} GB",
                f"{speed} MHz" if speed else None,
                row.get("Manufacturer"),
                row.get("PartNumber"),
            ),
        )

    for row in inventory["disks"]:
        size = _gb(row.get("Size"))
        add(
            "Disk",
            _join(
                row.get("FriendlyName"),
                "—",
                f"{size} GB" if size else None,
                row.get("MediaType"),
                row.get("BusType"),
                f"(health: {row.get('HealthStatus')})"
                if row.get("HealthStatus")
                else None,
            ),
        )

    for row in inventory["graphics"]:
        width = row.get("CurrentHorizontalResolution")
        height = row.get("CurrentVerticalResolution")
        refresh = row.get("CurrentRefreshRate")
        display = (
            f"driving {width}x{height} at {refresh} Hz"
            if width and height
            else None
        )
        add(
            "Graphics",
            _join(
                row.get("Name"),
                f"(driver {row.get('DriverVersion')})",
                display,
            ),
        )

    for row in inventory["network_adapters"]:
        speed = row.get("Speed")
        state = (
            f"connected at {round(int(speed) / 1_000_000)} Mbps"
            if row.get("NetEnabled") and speed
            else "not connected"
        )
        add("Network", f"{row.get('Name')} — {state}")

    for row in inventory["sound_devices"]:
        add("Audio", row.get("Name"))

    return lines
