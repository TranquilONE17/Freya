import json

import pytest

from freya import window as window_module
from freya.control_plane import build_local_control_plane
from freya.events import EventBus
from freya.image.gallery import ImageGallery
from freya.providers.image import comfyui
from freya.settings import Settings
from freya.window import FreyaWindow, WindowActions, build_status


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def test_bus_delivers_events_and_keeps_the_conversation():
    bus = EventBus()
    seen = []
    bus.subscribe(seen.append)

    bus.publish("user", text="hi", source="voice")
    bus.publish("status", status={"microphone": "muted"})
    bus.publish("assistant_chunk", text="Hello.")

    assert [e["type"] for e in seen] == ["user", "status", "assistant_chunk"]
    assert seen[0]["text"] == "hi" and seen[0]["time"] > 0
    # Status is not part of the conversation that gets replayed.
    assert [e["type"] for e in bus.history()] == ["user", "assistant_chunk"]


def test_bus_drops_a_subscriber_that_fails():
    bus = EventBus()
    seen = []

    def broken(event):
        raise RuntimeError("window went away")

    bus.subscribe(broken)
    bus.subscribe(seen.append)

    bus.publish("notice", text="one")
    bus.publish("notice", text="two")

    assert [e["text"] for e in seen] == ["one", "two"]
    assert bus._subscribers == [seen.append]


def test_bus_history_is_bounded():
    bus = EventBus(history_limit=3)

    for index in range(5):
        bus.publish("notice", text=str(index))

    assert [e["text"] for e in bus.history()] == ["2", "3", "4"]


def test_gallery_stores_images_newest_first_and_reloads(tmp_path):
    gallery = ImageGallery(tmp_path / "images")

    first = gallery.add("a fox", PNG, seed=7)
    second = gallery.add("an owl", JPEG)

    assert first["file"].endswith(".png") and second["file"].endswith(".jpg")
    assert first["seed"] == 7 and first["prompt"] == "a fox"
    assert [i["id"] for i in gallery.list()] == [second["id"], first["id"]]
    assert gallery.read(first["id"]) == ("image/png", PNG)

    reloaded = ImageGallery(tmp_path / "images")

    assert [i["id"] for i in reloaded.list()] == [second["id"], first["id"]]


def test_gallery_rejects_things_that_are_not_images(tmp_path):
    gallery = ImageGallery(tmp_path / "images")

    for data in (b"", b"<html>", b"MZ\x90\x00", b"#!/bin/sh"):
        with pytest.raises(ValueError):
            gallery.add("x", data)

    assert gallery.list() == []
    assert not (tmp_path / "images").exists()


@pytest.mark.parametrize(
    "image_id",
    ["", "index.json", "../index.json", "0" * 32, "Z" * 32, None, 7, "a" * 31],
)
def test_gallery_reads_only_known_ids(tmp_path, image_id):
    gallery = ImageGallery(tmp_path / "images")
    gallery.add("a fox", PNG)

    assert gallery.read(image_id) is None


def test_gallery_ignores_a_damaged_index_and_missing_files(tmp_path):
    directory = tmp_path / "images"
    gallery = ImageGallery(directory)
    kept = gallery.add("kept", PNG)
    lost = gallery.add("lost", PNG)
    (directory / lost["file"]).unlink()

    index = json.loads((directory / "index.json").read_text(encoding="utf-8"))
    index.append({"id": "../../evil", "file": "../../pyproject.toml"})
    index.append("nonsense")
    (directory / "index.json").write_text(json.dumps(index), encoding="utf-8")

    assert [i["id"] for i in ImageGallery(directory).list()] == [kept["id"]]

    (directory / "index.json").write_text("not json", encoding="utf-8")

    assert ImageGallery(directory).list() == []


def test_long_prompts_are_shortened(tmp_path):
    gallery = ImageGallery(tmp_path / "images")

    assert len(gallery.add("x" * 5000, PNG)["prompt"]) == 2000


class FakeListener:
    def __init__(self, running=True, muted=False):
        self.running = running
        self.muted = muted


@pytest.fixture
def plane(tmp_path, fake_ollama, monkeypatch):
    monkeypatch.setattr(
        comfyui, "check_comfyui_health", lambda url: comfyui.ProviderHealth.OFFLINE
    )
    monkeypatch.setattr(
        comfyui,
        "find_launch_plan",
        lambda url, configured=None: comfyui.LaunchPlan(["x"], headless=True),
    )
    plane = build_local_control_plane(tmp_path / "control.db", None)
    yield plane
    plane.close()


def test_status_for_the_window(plane, tmp_path):
    settings = Settings(tmp_path / "settings.json")
    settings.add_wake_name("computer")

    status = build_status(FakeListener(), settings, plane)

    assert status == {
        "microphone": "listening",
        "names": ["Freya", "Computer"],
        "model": "healthy",
        "images": "startable",
        "volume": 100,
    }
    assert build_status(FakeListener(muted=True), settings, plane)[
        "microphone"
    ] == "muted"
    assert build_status(FakeListener(running=False), settings, plane)[
        "microphone"
    ] == "off"
    assert build_status(None, settings, plane)["microphone"] == "off"


def make_window(tmp_path, opener):
    bus = EventBus()
    actions = WindowActions(
        say=lambda text: None,
        generate_image=lambda prompt: None,
        set_muted=lambda muted: None,
        interrupt=lambda: None,
        status=lambda: {},
    )
    return FreyaWindow(
        bus, ImageGallery(tmp_path / "images"), actions, port=0, opener=opener
    )


def test_window_opens_with_a_fresh_single_use_address(tmp_path):
    opened = []
    window = make_window(tmp_path, lambda url: opened.append(url) or "window")

    assert window.open() == "Freya's window is not available."
    assert window.start() is True

    try:
        assert window.open() == "Freya's window is open."
        assert window.open() == "Freya's window is open."
    finally:
        window.stop()

    assert len(opened) == 2 and opened[0] != opened[1]
    assert all(
        url.startswith(f"http://127.0.0.1:{window.port}/open?key=")
        for url in opened
    )


@pytest.mark.parametrize(
    "shown, message",
    [
        ("browser", "Freya's window is open in your browser."),
        ("none", "Freya's window could not be opened."),
    ],
)
def test_window_reports_how_it_was_shown(tmp_path, shown, message):
    window = make_window(tmp_path, lambda url: shown)
    window.start()

    try:
        assert window.open() == message
    finally:
        window.stop()


class FakeGateway:
    def __init__(self):
        self.idle = 0.0
        self.ever_connected = False
        self.port = 1

    def idle_seconds(self):
        return self.idle

    def start(self):
        pass

    def stop(self):
        pass


def test_window_counts_as_closed_only_after_a_grace_period(tmp_path):
    window = make_window(tmp_path, lambda url: "window")
    gateway = FakeGateway()
    window._gateway = gateway

    # Not started at all: there is no window.
    assert window.closed() is True

    window.running = True

    # Waiting for the window to appear for the first time.
    gateway.idle = 30
    assert window.closed() is False
    gateway.idle = window_module.OPEN_TIMEOUT_SECONDS + 1
    assert window.closed() is True

    # Connected.
    gateway.ever_connected = True
    gateway.idle = None
    assert window.closed() is False

    # Closed a moment ago, as during a page reload.
    gateway.idle = 2
    assert window.closed() is False

    # Closed for good.
    gateway.idle = window_module.CLOSE_GRACE_SECONDS + 1
    assert window.closed() is True


def test_single_instance_claim(monkeypatch):
    import subprocess
    import sys

    from freya import single_instance

    monkeypatch.setattr(
        single_instance, "MUTEX_NAME", "Local\\FreyaAssistantTest"
    )
    monkeypatch.setattr(single_instance, "_handle", None)
    monkeypatch.delenv("FREYA_ALLOW_MULTIPLE", raising=False)

    assert single_instance.claim() is True
    assert single_instance.claim() is True

    probe = (
        "from freya import single_instance as s;"
        "s.MUTEX_NAME='Local\\\\FreyaAssistantTest';"
        "print(s.claim())"
    )
    second = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={k: v for k, v in __import__("os").environ.items() if k != "FREYA_ALLOW_MULTIPLE"},
    )
    allowed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "FREYA_ALLOW_MULTIPLE": "1"},
    )

    if sys.platform == "win32":
        assert second.stdout.strip() == "False"
    assert allowed.stdout.strip() == "True"


def test_app_window_uses_its_own_browser_profile(tmp_path, monkeypatch):
    edge = tmp_path / "msedge.exe"
    edge.write_text("")
    launched = []
    monkeypatch.setattr(window_module, "_edge_path", lambda: edge)
    monkeypatch.setattr(
        window_module.subprocess,
        "Popen",
        lambda command, **kwargs: launched.append(command),
    )

    shown = window_module.open_app_window(
        "http://127.0.0.1:8770/open?key=abc", tmp_path / "profile"
    )

    assert shown == "window"
    assert launched[0][0] == str(edge)
    assert "--app=http://127.0.0.1:8770/open?key=abc" in launched[0]
    assert f"--user-data-dir={tmp_path / 'profile'}" in launched[0]


def test_app_window_falls_back_to_the_browser(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(window_module, "_edge_path", lambda: None)
    monkeypatch.setattr(
        window_module.webbrowser, "open", lambda url: opened.append(url) or True
    )

    assert window_module.open_app_window("http://127.0.0.1:1/x") == "browser"
    assert opened == ["http://127.0.0.1:1/x"]

    monkeypatch.setattr(window_module.webbrowser, "open", lambda url: False)

    assert window_module.open_app_window("http://127.0.0.1:1/x") == "none"


# -- how loudly she speaks ----------------------------------------------


def test_voice_volume_is_remembered_and_kept_in_range(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings(path)

    assert settings.voice_volume == 100
    assert settings.set_voice_volume(35) == 35
    assert settings.set_voice_volume(250) == 100
    assert settings.set_voice_volume(-4) == 0
    assert settings.set_voice_volume(42.6) == 43

    for bad in ("loud", None, True, float("nan"), [50]):
        with pytest.raises(ValueError):
            settings.set_voice_volume(bad)

    # It survives a restart, and changing it does not lose her names.
    settings.add_wake_name("computer")
    again = Settings(path)
    assert again.voice_volume == 43
    assert again.wake_names == ["freya", "computer"]


def test_damaged_volume_setting_falls_back_to_full(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"wake_names": ["freya", "nova"], "voice_volume": "eleven"}', encoding="utf-8")

    settings = Settings(path)

    assert settings.voice_volume == 100
    assert settings.wake_names == ["freya", "nova"]


def test_speech_is_played_at_the_chosen_volume(monkeypatch):
    import threading

    import numpy as np

    from freya.voice import tts

    played = []

    class Stream:
        active = False

    monkeypatch.setattr(tts.sd, "play", lambda audio, rate, blocking=False: played.append(np.array(audio)))
    monkeypatch.setattr(tts.sd, "get_stream", lambda: Stream())

    voice = tts.FreyaVoice.__new__(tts.FreyaVoice)
    voice.volume = 1.0
    voice.speech_listener = None
    voice._speaking_event = threading.Event()
    voice._interrupt_event = threading.Event()
    audio = np.full(8, 0.5, dtype=np.float32)

    voice._play_audio(audio)
    voice.set_volume(40)
    voice._play_audio(audio)
    voice.set_volume(0)
    voice._play_audio(audio)
    voice.set_volume(900)
    voice._play_audio(audio)

    assert [round(float(clip[0]), 3) for clip in played] == [0.5, 0.2, 0.0, 0.5]
    # The generated audio itself is left as it was.
    assert float(audio[0]) == 0.5
