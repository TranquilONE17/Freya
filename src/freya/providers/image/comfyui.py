import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import psutil

from freya.core.providers import (
    ProviderDefinition,
    ProviderHealth,
)


COMFYUI_PROVIDER = "comfyui-local"

IMAGE_GENERATE = "image.generate"

HEALTH_TIMEOUT_SECONDS = 2
START_TIMEOUT_SECONDS = 180
START_POLL_SECONDS = 1.0
STOP_TIMEOUT_SECONDS = 10


@dataclass
class LaunchPlan:
    """
    How Freya will start ComfyUI.

    headless is True when Freya runs the ComfyUI server itself, with
    no application window. That server belongs to Freya, so she stops
    it when she exits.
    """

    command: List[str]
    cwd: Optional[str] = None
    headless: bool = False


def _local_app_data() -> Path:
    return Path(
        os.environ.get("LOCALAPPDATA")
        or Path.home() / "AppData" / "Local"
    )


def _roaming_app_data() -> Path:
    return Path(
        os.environ.get("APPDATA")
        or Path.home() / "AppData" / "Roaming"
    )


def _desktop_app() -> Path:
    return (
        Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        / "Comfy Desktop"
        / "Comfy Desktop.exe"
    )


def _port(url) -> int:
    return urllib.parse.urlparse(url).port or 8188


def find_server_plan(url) -> Optional[LaunchPlan]:
    """
    Work out how to run the ComfyUI server that Comfy Desktop
    installed, using the same models and input/output folders the
    application uses. Returns None when no such install is found.
    """
    installs = _local_app_data() / "Comfy-Desktop" / "ComfyUI-Installs"

    if not installs.is_dir():
        return None

    for install in sorted(installs.iterdir()):
        python = install / "ComfyUI" / ".venv" / "Scripts" / "python.exe"
        main = install / "ComfyUI" / "main.py"

        if not (python.is_file() and main.is_file()):
            continue

        command = [
            str(python),
            "-s",
            str(Path("ComfyUI") / "main.py"),
            "--port",
            str(_port(url)),
            "--disable-auto-launch",
        ]

        model_configs = sorted(
            (
                _roaming_app_data()
                / "Comfy Desktop"
                / "instance-model-paths"
            ).glob("*.yaml"),
            key=lambda path: path.stat().st_mtime,
        )

        if model_configs:
            command += [
                "--extra-model-paths-config",
                str(model_configs[-1]),
            ]

        shared = _local_app_data() / "Comfy-Desktop" / "ComfyUI-Shared"

        for flag, folder in (
            ("--input-directory", shared / "input"),
            ("--output-directory", shared / "output"),
        ):
            if folder.is_dir():
                command += [flag, str(folder)]

        return LaunchPlan(
            command=command,
            cwd=str(install),
            headless=True,
        )

    return None


def find_launch_plan(url, configured=None) -> Optional[LaunchPlan]:
    """
    Decide how to start ComfyUI, or return None when Freya does not
    know how.

    A configured program wins. Otherwise the server is run directly,
    which needs nobody at the screen. Opening the Comfy Desktop
    application is the last resort, because it waits for a click
    before it starts its server.
    """
    if configured:
        return LaunchPlan(command=[configured])

    plan = find_server_plan(url)

    if plan is not None:
        return plan

    if _desktop_app().is_file():
        return LaunchPlan(command=[str(_desktop_app())])

    return None


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


def _launch(plan: LaunchPlan, log_path=None):
    """
    Start the planned program and return its process.

    A headless server gets no console window and writes its output to
    the log file. An application is started detached, so it keeps
    running after Freya exits.
    """
    flags = 0
    output = subprocess.DEVNULL

    if plan.headless:
        if os.name == "nt":
            flags = subprocess.CREATE_NO_WINDOW

        if log_path is not None:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            output = open(log_path, "w", encoding="utf-8")
    elif os.name == "nt":
        flags = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )

    try:
        return subprocess.Popen(
            plan.command,
            cwd=plan.cwd,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            close_fds=True,
        )
    finally:
        if output is not subprocess.DEVNULL:
            output.close()


def _stop_process_tree(process) -> None:
    """
    Stop a process Freya started, along with anything it started.
    """
    try:
        parent = psutil.Process(process.pid)
    except psutil.NoSuchProcess:
        return

    family = parent.children(recursive=True) + [parent]

    for member in family:
        try:
            member.terminate()
        except psutil.NoSuchProcess:
            pass

    _, alive = psutil.wait_procs(family, timeout=STOP_TIMEOUT_SECONDS)

    for member in alive:
        try:
            member.kill()
        except psutil.NoSuchProcess:
            pass


class ComfyUIServer:
    """
    Starts ComfyUI when it is needed and stops it again if, and only
    if, Freya was the one who started its server.
    """

    def __init__(
        self,
        url,
        configured_command=None,
        log_path=None,
        timeout=START_TIMEOUT_SECONDS,
        launch=None,
        stop_process=None,
        sleep=None,
        clock=None,
    ):
        self.url = url
        self.plan = find_launch_plan(url, configured_command)
        self._log_path = log_path
        self._timeout = timeout
        self._launch = launch or _launch
        self._stop_process = stop_process or _stop_process_tree
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._process = None

    @property
    def owns_server(self) -> bool:
        return self._process is not None

    def health(self):
        return check_comfyui_health(self.url)

    def start(self) -> str:
        """
        Make sure the ComfyUI server is answering, starting it when it
        is not. Raises RuntimeError when it cannot be started or does
        not come up in time.
        """
        if self.health() == ProviderHealth.HEALTHY:
            return "already running"

        if self.plan is None:
            raise RuntimeError(
                "ComfyUI is not running and Freya does not know how "
                "to start it. Start it yourself, or set "
                "FREYA_COMFYUI_COMMAND to the program that starts it."
            )

        # A server Freya started earlier that has stopped answering.
        self.stop()

        try:
            process = self._launch(self.plan, self._log_path)
        except OSError as exc:
            raise RuntimeError(
                f"ComfyUI could not be started: {exc}"
            ) from exc

        if self.plan.headless:
            self._process = process

        deadline = self._clock() + self._timeout

        while self._clock() < deadline:
            self._sleep(START_POLL_SECONDS)

            if self.health() == ProviderHealth.HEALTHY:
                return "started"

            if (
                self.plan.headless
                and process is not None
                and process.poll() is not None
            ):
                self._process = None
                raise RuntimeError(
                    "The ComfyUI server stopped while starting up"
                    + self._log_hint()
                )

        self.stop()

        if self.plan.headless:
            raise RuntimeError(
                "The ComfyUI server did not become ready within "
                f"{self._timeout:.0f} seconds" + self._log_hint()
            )

        raise RuntimeError(
            "ComfyUI was opened but did not become ready within "
            f"{self._timeout:.0f} seconds. It may be waiting for you "
            "in its own window."
        )

    def stop(self) -> str:
        """
        Stop the server if Freya started it. A ComfyUI the owner
        started is left alone.
        """
        if self._process is None:
            return "not ours"

        process, self._process = self._process, None
        self._stop_process(process)

        return "stopped"

    def _log_hint(self) -> str:
        if self._log_path is None:
            return "."

        return f". Its output is in {self._log_path}."


def create_comfyui_provider(server: ComfyUIServer):
    """
    Describe the local ComfyUI server as an image provider.
    """
    return ProviderDefinition(
        provider_id=COMFYUI_PROVIDER,
        name="Local ComfyUI image server",
        capabilities=[IMAGE_GENERATE],
        start_handler=server.start,
        stop_handler=server.stop,
        health_handler=server.health,
        metadata={
            "url": server.url,
            "can_start": server.plan is not None,
            "headless": bool(server.plan and server.plan.headless),
        },
    )
