import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from freya.core.providers import (
    ProviderDefinition,
    ProviderHealth,
)


COMFYUI_PROVIDER = "comfyui-local"

IMAGE_GENERATE = "image.generate"

# Where the Comfy Desktop installer puts the application on Windows.
DEFAULT_LAUNCHERS = (
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "Comfy Desktop"
    / "Comfy Desktop.exe",
)

HEALTH_TIMEOUT_SECONDS = 2
START_TIMEOUT_SECONDS = 180
START_POLL_SECONDS = 1.0


def check_comfyui_health(url):
    """
    HEALTHY when the ComfyUI server answers, otherwise OFFLINE.
    """
    try:
        with urllib.request.urlopen(
            f"{url.rstrip('/')}/system_stats",
            timeout=HEALTH_TIMEOUT_SECONDS,
        ) as response:
            json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return ProviderHealth.OFFLINE

    return ProviderHealth.HEALTHY


def find_comfyui_launcher(configured=None):
    """
    Return the command that starts ComfyUI as a list of arguments, or
    None when Freya does not know how to start it.

    A configured command wins. Otherwise the standard Comfy Desktop
    location is used when the application is installed there.
    """
    if configured:
        return [configured]

    for candidate in DEFAULT_LAUNCHERS:
        if candidate.exists():
            return [str(candidate)]

    return None


def _launch(command):
    """
    Start ComfyUI as its own program, so it keeps running after Freya
    exits and is not tied to her console window.
    """
    flags = 0

    if os.name == "nt":
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )

    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def start_comfyui(
    url,
    command,
    timeout=START_TIMEOUT_SECONDS,
    launch=None,
    sleep=None,
    clock=None,
):
    """
    Make sure the ComfyUI server is answering, starting the
    application when it is not. Raises RuntimeError when it cannot be
    started or does not come up in time.
    """
    launch = launch or _launch
    sleep = sleep or time.sleep
    clock = clock or time.monotonic

    if check_comfyui_health(url) == ProviderHealth.HEALTHY:
        return "already running"

    if not command:
        raise RuntimeError(
            "ComfyUI is not running and Freya does not know how to "
            "start it. Start it yourself, or set "
            "FREYA_COMFYUI_COMMAND to the program that starts it."
        )

    try:
        launch(command)
    except OSError as exc:
        raise RuntimeError(
            f"ComfyUI could not be started: {exc}"
        ) from exc

    deadline = clock() + timeout

    while clock() < deadline:
        sleep(START_POLL_SECONDS)

        if check_comfyui_health(url) == ProviderHealth.HEALTHY:
            return "started"

    raise RuntimeError(
        "ComfyUI was started but did not become ready within "
        f"{timeout:.0f} seconds. It may be waiting for you in its "
        "own window."
    )


def create_comfyui_provider(url, configured_command=None):
    """
    Describe the local ComfyUI server as an image provider.

    Freya starts it on demand but never stops it: it is the owner's
    application and may be in use outside Freya.
    """
    command = find_comfyui_launcher(configured_command)

    return ProviderDefinition(
        provider_id=COMFYUI_PROVIDER,
        name="Local ComfyUI image server",
        capabilities=[IMAGE_GENERATE],
        start_handler=lambda: start_comfyui(url, command),
        health_handler=lambda: check_comfyui_health(url),
        metadata={
            "url": url,
            "can_start": command is not None,
        },
    )
