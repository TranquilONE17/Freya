import os
import platform
import shutil
import subprocess

from freya.tools.tool_registry import (
    ToolDefinition,
)


def _bytes_to_gb(value):
    return round(
        value / 1024 / 1024 / 1024,
        2,
    )


def get_system_info():
    """
    Return basic information about Freya's host system.
    """

    return {
        "computer_name": (
            platform.node()
        ),
        "operating_system": (
            platform.system()
        ),
        "os_release": (
            platform.release()
        ),
        "os_version": (
            platform.version()
        ),
        "architecture": (
            platform.machine()
        ),
        "processor": (
            platform.processor()
        ),
        "python_version": (
            platform.python_version()
        ),
    }


def get_disk_info():
    """
    Return disk usage for the drive containing
    the Freya project.
    """

    project_drive = os.path.splitdrive(
        os.getcwd()
    )[0]

    if project_drive:
        disk_path = project_drive + "\\"
    else:
        disk_path = os.getcwd()

    usage = shutil.disk_usage(
        disk_path
    )

    return {
        "drive": disk_path,
        "total_gb": _bytes_to_gb(
            usage.total
        ),
        "used_gb": _bytes_to_gb(
            usage.used
        ),
        "free_gb": _bytes_to_gb(
            usage.free
        ),
    }


def get_gpu_info():
    """
    Query NVIDIA GPU status using nvidia-smi.

    This is read-only.
    """

    command = [
        "nvidia-smi",
        "--query-gpu="
        "name,"
        "temperature.gpu,"
        "utilization.gpu,"
        "memory.total,"
        "memory.used,"
        "memory.free",
        "--format=csv,noheader,nounits",
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    output = completed.stdout.strip()

    if not output:
        raise RuntimeError(
            "nvidia-smi returned no GPU data."
        )

    gpus = []

    for index, line in enumerate(
        output.splitlines()
    ):
        parts = [
            part.strip()
            for part in line.split(",")
        ]

        if len(parts) != 6:
            raise RuntimeError(
                "Unexpected nvidia-smi output: "
                f"{line}"
            )

        (
            name,
            temperature,
            utilization,
            memory_total,
            memory_used,
            memory_free,
        ) = parts

        gpus.append(
            {
                "index": index,
                "name": name,
                "temperature_c": int(
                    temperature
                ),
                "utilization_percent": int(
                    utilization
                ),
                "memory_total_mib": int(
                    memory_total
                ),
                "memory_used_mib": int(
                    memory_used
                ),
                "memory_free_mib": int(
                    memory_free
                ),
            }
        )

    return gpus


def register_system_tools(
    registry,
):
    """
    Register Freya's read-only local system tools.
    """

    registry.register(
        ToolDefinition(
            name="system.info",
            description=(
                "Returns basic information about "
                "Freya's host computer and "
                "operating system."
            ),
            handler=get_system_info,
            category="system",
            aliases=[
                "system",
                "computer.info",
            ],
        )
    )

    registry.register(
        ToolDefinition(
            name="system.disk",
            description=(
                "Returns total, used, and free "
                "disk space for Freya's "
                "current drive."
            ),
            handler=get_disk_info,
            category="system",
            aliases=[
                "disk",
                "disk.info",
            ],
        )
    )

    registry.register(
        ToolDefinition(
            name="system.gpu",
            description=(
                "Returns NVIDIA GPU name, "
                "temperature, utilization, "
                "and VRAM usage."
            ),
            handler=get_gpu_info,
            category="system",
            aliases=[
                "gpu",
                "gpu.status",
            ],
        )
    )