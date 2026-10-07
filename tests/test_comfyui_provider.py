import urllib.error

import pytest

from freya.control_plane import build_local_control_plane
from freya.core.providers import ProviderHealth, ProviderState
from freya.image.image_generator import FreyaImageGenerator
from freya.providers.image import comfyui
from freya.providers.image.comfyui import COMFYUI_PROVIDER


URL = "http://127.0.0.1:8188"


class FakeResponse:
    def read(self):
        return b'{"system": {}}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeComfy:
    """A ComfyUI that can be down, up, or come up some time after launch."""

    def __init__(self, monkeypatch):
        self.up = False
        self.launched = []
        self.ready_after_polls = 3
        self.polls_since_launch = 0
        self.launch_error = None
        self.now = 0.0
        monkeypatch.setattr(comfyui.urllib.request, "urlopen", self.urlopen)
        monkeypatch.setattr(comfyui, "_launch", self.launch)
        monkeypatch.setattr(comfyui.time, "sleep", self.sleep)
        monkeypatch.setattr(comfyui.time, "monotonic", lambda: self.now)

    def urlopen(self, url, timeout=None):
        assert url == f"{URL}/system_stats"
        if not self.up:
            raise urllib.error.URLError("connection refused")
        return FakeResponse()

    def launch(self, command):
        if self.launch_error:
            raise self.launch_error
        self.launched.append(command)

    def sleep(self, seconds):
        self.now += seconds
        if self.launched and self.ready_after_polls is not None:
            self.polls_since_launch += 1
            if self.polls_since_launch >= self.ready_after_polls:
                self.up = True


@pytest.fixture
def comfy(monkeypatch):
    return FakeComfy(monkeypatch)


def start(comfy, command=("comfy.exe",), **kwargs):
    # Pass the patched helpers explicitly: the function's defaults were
    # bound when the module was imported.
    return comfyui.start_comfyui(
        URL,
        list(command) if command else None,
        launch=comfy.launch,
        sleep=comfy.sleep,
        clock=lambda: comfy.now,
        **kwargs,
    )


def test_health_reflects_whether_the_server_answers(comfy):
    assert comfyui.check_comfyui_health(URL) == ProviderHealth.OFFLINE

    comfy.up = True

    assert comfyui.check_comfyui_health(URL + "/") == ProviderHealth.HEALTHY


def test_nothing_is_launched_when_already_running(comfy):
    comfy.up = True

    assert start(comfy) == "already running"
    assert comfy.launched == []


def test_starts_comfyui_and_waits_until_it_answers(comfy):
    assert start(comfy) == "started"

    assert comfy.launched == [["comfy.exe"]]
    assert comfy.now == 3.0


def test_gives_up_when_it_never_becomes_ready(comfy):
    comfy.ready_after_polls = None

    with pytest.raises(RuntimeError) as error:
        start(comfy, timeout=10)

    assert "did not become ready within 10 seconds" in str(error.value)
    assert comfy.launched == [["comfy.exe"]]
    assert comfy.now == 10.0


def test_explains_when_it_does_not_know_how_to_start(comfy):
    with pytest.raises(RuntimeError) as error:
        start(comfy, command=None)

    assert "FREYA_COMFYUI_COMMAND" in str(error.value)
    assert comfy.launched == []


def test_launch_failure_is_reported(comfy):
    comfy.launch_error = FileNotFoundError("comfy.exe not found")

    with pytest.raises(RuntimeError) as error:
        start(comfy)

    assert "could not be started" in str(error.value)


def test_launcher_prefers_the_configured_command(tmp_path, monkeypatch):
    installed = tmp_path / "Comfy Desktop.exe"
    installed.write_text("")
    monkeypatch.setattr(comfyui, "DEFAULT_LAUNCHERS", (installed,))

    assert comfyui.find_comfyui_launcher("D:\\tools\\comfy.bat") == [
        "D:\\tools\\comfy.bat"
    ]
    assert comfyui.find_comfyui_launcher() == [str(installed)]

    monkeypatch.setattr(
        comfyui, "DEFAULT_LAUNCHERS", (tmp_path / "missing.exe",)
    )

    assert comfyui.find_comfyui_launcher() is None


@pytest.fixture
def plane(tmp_path, fake_ollama, comfy, monkeypatch):
    monkeypatch.setattr(
        "freya.control_plane.COMFYUI_COMMAND", "comfy.exe"
    )
    plane = build_local_control_plane(tmp_path / "control.db", None)
    yield plane
    plane.close()


def test_comfyui_is_not_started_at_startup(plane, comfy):
    provider = plane.providers.get(COMFYUI_PROVIDER)

    assert comfy.launched == []
    assert provider.state == ProviderState.STOPPED
    assert provider.metadata["can_start"] is True
    assert plane.startup_messages() == []


def test_image_request_starts_comfyui_when_it_is_down(plane, comfy):
    said = []

    plane.ensure_image_backend(announce=said.append)

    provider = plane.providers.get(COMFYUI_PROVIDER)

    assert comfy.launched == [["comfy.exe"]]
    assert provider.state == ProviderState.RUNNING
    assert provider.health == ProviderHealth.HEALTHY
    assert "starting it" in said[0]
    assert said[-1] == "Freya: ComfyUI is ready."


def test_image_request_does_nothing_when_comfyui_is_already_up(plane, comfy):
    comfy.up = True
    said = []

    plane.ensure_image_backend(announce=said.append)
    plane.ensure_image_backend(announce=said.append)

    assert comfy.launched == []
    assert said == []
    assert plane.providers.get(COMFYUI_PROVIDER).state == ProviderState.RUNNING


def test_comfyui_is_restarted_if_it_was_closed_later(plane, comfy):
    plane.ensure_image_backend(announce=lambda message: None)

    comfy.up = False
    comfy.polls_since_launch = 0

    plane.ensure_image_backend(announce=lambda message: None)

    assert len(comfy.launched) == 2
    assert plane.providers.get(COMFYUI_PROVIDER).health == ProviderHealth.HEALTHY


def test_failure_to_start_is_raised_with_the_reason(plane, comfy):
    comfy.launch_error = FileNotFoundError("comfy.exe not found")

    with pytest.raises(RuntimeError) as error:
        plane.ensure_image_backend(announce=lambda message: None)

    provider = plane.providers.get(COMFYUI_PROVIDER)

    assert "could not be started" in str(error.value)
    assert provider.state == ProviderState.FAILED

    # A later request can try again.
    comfy.launch_error = None
    plane.ensure_image_backend(announce=lambda message: None)

    assert provider.state == ProviderState.RUNNING


def test_image_generator_calls_its_ensure_hook():
    calls = []

    FreyaImageGenerator(ensure_running=lambda: calls.append(1)).ensure_running()
    FreyaImageGenerator().ensure_running()

    assert calls == [1]
