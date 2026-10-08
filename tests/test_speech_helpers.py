import json
import sys
import time
from pathlib import Path

import numpy as np
import psutil
import pytest

from freya.speech import helper as helper_module
from freya.speech.chatterbox_engine import ChatterboxEngine
from freya.speech.engines import (
    ROLE_CLONE,
    ROLE_DESIGN,
    ROLE_PRESET,
    STATUS_NOT_INSTALLED,
    STATUS_READY,
    SpeechError,
)
from freya.speech.helper import HelperProcess
from freya.speech.qwen_engine import QwenEngine
from freya.speech.references import (
    MAX_SECONDS,
    MIN_SECONDS,
    ReferenceStore,
)
from freya.speech.store import ClipStore, VoiceProfileStore
from freya.speech.studio import VoiceStudio


FAKE_WORKER = Path(__file__).with_name("fake_speech_worker.py")
RATE = 24000


def recording(seconds=8.0, level=0.3, rate=RATE) -> bytes:
    """Mono 16-bit samples, as the window sends them."""
    samples = np.sin(np.arange(int(rate * seconds)) / 20.0) * level

    return (samples * 32767).astype("<i2").tobytes()


@pytest.fixture(autouse=True)
def worker_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("FREYA_TEST_WORKERS", str(helper_module.WORKERS_DIR))
    # Helper logs go to a scratch folder, not Freya's data folder.
    monkeypatch.setattr(helper_module, "DATA_DIR", tmp_path / "data")


@pytest.fixture
def references(tmp_path):
    return ReferenceStore(tmp_path / "references")


@pytest.fixture
def upload(references):
    return references.add_upload(recording(), RATE, True, "What was said.")


@pytest.fixture
def helper(tmp_path):
    process = HelperProcess(
        sys.executable,
        FAKE_WORKER,
        log_path=tmp_path / "helper.log",
        idle_seconds=0,
    )
    yield process
    process.stop()


def fake(engine_class, references, **options):
    engine = engine_class(
        references,
        python=sys.executable,
        script=FAKE_WORKER,
        idle_seconds=0,
        **options,
    )

    return engine


@pytest.fixture
def chatterbox(references):
    engine = fake(ChatterboxEngine, references)
    yield engine
    engine.unload()


@pytest.fixture
def qwen(references):
    engine = fake(QwenEngine, references)
    yield engine
    engine.unload()


# -- recordings --------------------------------------------------------


def test_recording_is_refused_without_the_owners_confirmation(references):
    for consent in (False, None, "yes", 1):
        with pytest.raises(SpeechError, match="right to use"):
            references.add_upload(recording(), RATE, consent)

    assert references.list() == []
    assert list(references.directory.glob("*.wav")) == []


def test_accepted_recording_records_the_confirmation(references, upload):
    kept = references.get(upload["id"])

    assert kept["origin"] == "upload"
    assert kept["consent"] is True
    assert kept["consent_time"] > 0
    assert kept["text"] == "What was said."
    assert kept["seconds"] == 8.0
    assert references.path(upload["id"]).is_file()


@pytest.mark.parametrize(
    "pcm, rate",
    [
        (recording(MIN_SECONDS - 1), RATE),
        (recording(MAX_SECONDS + 2), RATE),
        (recording(level=0.0), RATE),
        (recording()[:-1], RATE),
        (recording(), 8000),
        (recording(), 96000),
        (recording(), "24000"),
        (recording(), True),
        ("not bytes", RATE),
        (None, RATE),
        (b"", RATE),
    ],
    ids=lambda value: type(value).__name__ + str(len(value))
    if isinstance(value, (bytes, str))
    else repr(value),
)
def test_unusable_recordings_are_refused(references, pcm, rate):
    with pytest.raises(SpeechError):
        references.add_upload(pcm, rate, True)

    assert references.list() == []


def test_recordings_survive_a_restart_and_unused_ones_can_be_dropped(
    references, upload
):
    designed = references.add_designed(
        np.zeros(RATE, "float32"), RATE, "qwen3-tts", "Hello."
    )

    again = ReferenceStore(references.directory)
    assert {r["id"] for r in again.list()} == {upload["id"], designed["id"]}

    again.keep_only([designed["id"], None])

    assert [r["id"] for r in again.list()] == [designed["id"]]
    assert not (references.directory / f"{upload['id']}.wav").exists()
    assert again.delete(designed["id"]) is True
    assert again.delete(designed["id"]) is False


def test_only_known_recordings_have_a_path(references, upload, tmp_path):
    (tmp_path / "secret.wav").write_bytes(b"RIFF")

    for asked in ("../secret", "a" * 32, None, 5, ["x"]):
        assert references.get(asked) is None
        assert references.path(asked) is None


def test_recording_missing_its_file_is_forgotten(references, upload):
    references.path(upload["id"]).unlink()

    assert ReferenceStore(references.directory).list() == []


# -- the helper process ------------------------------------------------


def test_helper_starts_on_first_use_and_ignores_library_chatter(helper, tmp_path):
    assert helper.running is False

    answer = helper.request(
        {"op": "synthesize", "output": str(tmp_path / "out.wav"), "text": "héllo"}
    )

    assert helper.running is True
    assert answer["ok"] is True
    assert "noise" not in answer
    assert answer["echo"]["text"] == "héllo"
    assert (tmp_path / "out.wav").is_file()
    assert "printed by a library" in (tmp_path / "helper.log").read_text()


def test_helper_is_reused_and_stopping_it_ends_the_process(helper):
    first = helper.request({"op": "pid"})["pid"]
    second = helper.request({"op": "pid"})["pid"]

    helper.stop()

    assert first == second
    assert helper.running is False
    assert not psutil.pid_exists(first)
    assert helper.request({"op": "pid"})["pid"] != first


def test_helper_failure_is_reported_and_it_keeps_working(helper):
    with pytest.raises(SpeechError, match="the model fell over"):
        helper.request({"op": "fail"})

    with pytest.raises(SpeechError):
        helper.request({"op": "no-such-operation"})

    assert helper.request({"op": "pid"})["ok"] is True


def test_helper_that_dies_is_noticed_and_restarted(helper):
    with pytest.raises(SpeechError, match="stopped unexpectedly"):
        helper.request({"op": "crash"})

    assert helper.running is False
    assert helper.request({"op": "pid"})["ok"] is True


def test_helper_that_takes_too_long_is_stopped(helper):
    pid = helper.request({"op": "pid"})["pid"]

    with pytest.raises(SpeechError, match="too long"):
        helper.request({"op": "sleep", "seconds": 30}, timeout=0.5)

    assert helper.running is False
    assert not psutil.pid_exists(pid)


def test_idle_helper_is_unloaded(tmp_path):
    helper = HelperProcess(sys.executable, FAKE_WORKER, idle_seconds=0.3)

    try:
        helper.request({"op": "pid"})
        deadline = time.monotonic() + 10

        while helper.running and time.monotonic() < deadline:
            time.sleep(0.05)

        assert helper.running is False
    finally:
        helper.stop()


def test_missing_interpreter_is_a_clear_error(tmp_path):
    helper = HelperProcess(tmp_path / "nowhere" / "python.exe", FAKE_WORKER)

    with pytest.raises(SpeechError, match="could not be started"):
        helper.request({"op": "pid"})


def test_helper_does_not_inherit_freyas_python_path(helper, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "C:/somewhere/else")
    monkeypatch.setenv("VIRTUAL_ENV", "C:/freya/.venv")

    # The fake worker would fail to start if it could not import its
    # own modules; what matters is that Freya's are not forced on it.
    assert helper.request({"op": "pid"})["ok"] is True


# -- Chatterbox --------------------------------------------------------


def test_engine_without_its_environment_is_not_installed(references, tmp_path):
    for engine_class in (ChatterboxEngine, QwenEngine):
        engine = engine_class(references, envs_dir=tmp_path / "none")

        assert engine.installed is False
        assert engine.info().status == STATUS_NOT_INSTALLED

        with pytest.raises(SpeechError, match="not installed"):
            engine._run("synthesize", text="Hello.")


def test_chatterbox_only_clones_and_offers_each_models_real_controls(chatterbox):
    info = chatterbox.info()
    models = {model["id"]: model for model in info.controls["models"]}

    assert info.status == STATUS_READY
    assert set(info.roles) == {ROLE_CLONE}
    assert "watermark" in info.detail
    assert set(models) == {"turbo", "multilingual", "nano"}
    # Turbo and Nano ignore expressiveness and pace, so neither is offered.
    assert models["turbo"]["controls"] == ["temperature"]
    assert models["nano"]["controls"] == ["temperature"]
    assert set(models["multilingual"]["controls"]) == {
        "temperature", "exaggeration", "cfg_weight",
    }
    assert [l["code"] for l in models["turbo"]["languages"]] == ["en"]
    assert len(models["multilingual"]["languages"]) == 23


def test_chatterbox_settings_keep_only_what_the_model_supports(
    chatterbox, upload
):
    turbo = chatterbox.validate(ROLE_CLONE, {
        "reference": upload["id"], "exaggeration": 1.2, "cfg_weight": 0.1,
        "watermark": False,
    })
    multilingual = chatterbox.validate(ROLE_CLONE, {
        "model": "multilingual", "language": "fr", "reference": upload["id"],
        "exaggeration": 0.7,
    })

    assert turbo == {
        "model": "turbo", "language": "en", "reference": upload["id"],
        "temperature": 0.8,
    }
    assert multilingual == {
        "model": "multilingual", "language": "fr", "reference": upload["id"],
        "temperature": 0.8, "exaggeration": 0.7, "cfg_weight": 0.5,
    }


def test_chatterbox_refuses_bad_settings(chatterbox, references, upload):
    designed = references.add_designed(
        np.zeros(RATE, "float32"), RATE, "qwen3-tts", "Hello."
    )

    for kind, settings in [
        (ROLE_PRESET, {"reference": upload["id"]}),
        (ROLE_DESIGN, {"reference": upload["id"]}),
        (ROLE_CLONE, None),
        (ROLE_CLONE, {}),
        (ROLE_CLONE, {"reference": "a" * 32}),
        (ROLE_CLONE, {"reference": designed["id"]}),
        (ROLE_CLONE, {"reference": upload["id"], "model": "giant"}),
        (ROLE_CLONE, {"reference": upload["id"], "model": "turbo", "language": "fr"}),
        (ROLE_CLONE, {"reference": upload["id"], "temperature": 9}),
        (ROLE_CLONE, {"reference": upload["id"], "model": "multilingual", "exaggeration": "lots"}),
    ]:
        with pytest.raises(SpeechError):
            chatterbox.validate(kind, settings)


def test_chatterbox_speaks_through_its_helper(chatterbox, references, upload):
    audio, rate = chatterbox.synthesize(
        "Hello.", ROLE_CLONE, {"reference": upload["id"]}
    )

    assert rate == 8000 and len(audio) == 4000
    assert audio.dtype == np.float32
    assert chatterbox.loaded is True
    assert chatterbox.last_metrics["generate_seconds"] == 0.01
    assert chatterbox.last_metrics["total_seconds"] >= 0

    chatterbox.unload()

    assert chatterbox.loaded is False


def test_helper_is_given_the_recording_and_told_to_stay_offline(
    chatterbox, references, upload
):
    sent = []
    real = chatterbox._helper.request

    def record(message, **options):
        sent.append(message)
        return real(message, **options)

    chatterbox._helper.request = record
    chatterbox.synthesize("Hello.", ROLE_CLONE, {"reference": upload["id"]})

    assert sent[0]["reference"] == str(references.path(upload["id"]))
    assert sent[0]["settings"]["model"] == "turbo"
    assert chatterbox._helper._environment["HF_HUB_OFFLINE"] == "1"
    # The temporary file the helper wrote into is gone.
    assert not Path(sent[0]["output"]).exists()


def test_room_is_made_on_the_graphics_card_only_before_loading(
    references, upload
):
    asked = []
    engine = fake(ChatterboxEngine, references, make_room=asked.append)

    try:
        engine.synthesize("Hello.", ROLE_CLONE, {"reference": upload["id"]})
        engine.synthesize("Hello.", ROLE_CLONE, {"reference": upload["id"]})
    finally:
        engine.unload()

    assert asked == [engine.gpu_megabytes_needed]


# -- Qwen3-TTS ---------------------------------------------------------


def test_qwen_designs_and_clones(qwen):
    info = qwen.info()

    assert set(info.roles) == {ROLE_DESIGN, ROLE_CLONE}
    assert info.controls["reference"] == {"transcript": True}
    assert {m["id"] for m in info.controls["models"]} == {"1.7b", "0.6b"}


def test_qwen_design_needs_a_description_in_a_supported_language(qwen):
    assert qwen.validate_design(
        {"description": "  a calm   low voice ", "language": "French"}
    ) == {"description": "a calm low voice", "language": "French"}

    for settings in (
        None,
        {},
        {"description": "   "},
        {"description": "x" * 401},
        {"description": "calm", "language": "Klingon"},
    ):
        with pytest.raises(SpeechError):
            qwen.validate_design(settings)


def test_qwen_designed_voice_must_come_from_its_own_sample(
    qwen, references, upload
):
    own = references.add_designed(
        np.zeros(RATE, "float32"), RATE, "qwen3-tts", "Hello."
    )
    other = references.add_designed(
        np.zeros(RATE, "float32"), RATE, "another-engine", "Hello."
    )
    design = {"description": "calm", "language": "English"}

    assert qwen.validate(ROLE_DESIGN, {**design, "reference": own["id"]}) == {
        "language": "English", "model": "1.7b", "description": "calm",
        "reference": own["id"],
    }

    for reference in (other["id"], upload["id"], None, "a" * 32):
        with pytest.raises(SpeechError):
            qwen.validate(ROLE_DESIGN, {**design, "reference": reference})

    # And a clone must come from a recording the owner supplied.
    with pytest.raises(SpeechError):
        qwen.validate(ROLE_CLONE, {"reference": own["id"]})

    with pytest.raises(SpeechError):
        qwen.validate(ROLE_PRESET, {"reference": upload["id"]})


def test_qwen_clone_passes_the_transcript_to_its_helper(qwen, upload):
    sent = []
    real = qwen._helper.request

    def record(message, **options):
        sent.append(message)
        return real(message, **options)

    qwen._helper.request = record
    qwen.synthesize("Hello.", ROLE_CLONE, {
        "reference": upload["id"], "model": "0.6b", "language": "English",
    })

    assert sent[0]["reference_text"] == "What was said."
    assert sent[0]["settings"]["model"] == "0.6b"


# -- the benchmark's scoring -------------------------------------------


def test_word_error_rate_counts_wrong_missing_and_extra_words():
    from freya.speech.benchmark import word_error_rate

    said = "The meeting is at nine, and it's eighteen degrees."

    assert word_error_rate(said, "the meeting is at 9:00 and it's 18 degrees") == 0
    assert word_error_rate(said, "The meeting is at five, and it's eighteen degrees.") == 0.111
    assert word_error_rate("a b c d", "a x c") == 0.5
    assert word_error_rate("a b", "a b c") == 0.5
    assert word_error_rate("", "anything") == 0


def test_install_plan_keeps_engines_out_of_freyas_environment():
    from freya.speech import install

    assert set(install.ENGINES) == {"chatterbox", "qwen3-tts"}
    # Chatterbox's source is pinned to an exact commit, and the package
    # its watermarker needs is part of the plan.
    steps = [" ".join(step) for step in install.ENGINES["chatterbox"]["steps"]]
    assert any(install.CHATTERBOX_COMMIT in step for step in steps)
    assert any("setuptools<81" in step for step in steps)
    assert len(install.CHATTERBOX_COMMIT) == 40

    for engine_id in install.ENGINES:
        python = helper_module.environment_python(engine_id)
        assert "speech_envs" in str(python)
        assert ".venv" not in python.parts


# -- the studio with the large engines ---------------------------------


@pytest.fixture
def studio(tmp_path, references, chatterbox, qwen):
    return VoiceStudio(
        [chatterbox, qwen],
        profiles=VoiceProfileStore(tmp_path / "voice_profiles.json"),
        clips=ClipStore(tmp_path / "clips"),
        references=references,
    )


def test_cloning_from_the_window_start_to_finish(studio):
    refused = studio.handle({
        "action": "reference", "upload": recording(), "sample_rate": RATE,
        "consent": False,
    })
    assert "right to use" in refused["error"]
    assert refused["reference"] is None

    sent = studio.handle({
        "action": "reference", "upload": recording(), "sample_rate": RATE,
        "consent": True, "transcript": "What was said.",
    })
    reference = sent["reference"]
    assert sent["error"] is None
    assert set(reference) == {"id", "origin", "seconds"}

    settings = {"model": "turbo", "reference": reference["id"]}
    preview = studio.handle({
        "action": "preview", "engine": "chatterbox", "kind": "clone",
        "settings": settings, "text": "Hello.",
    })
    assert preview["error"] is None
    assert studio.clips.read(preview["clip"]["id"])

    saved = studio.handle({
        "action": "save", "engine": "chatterbox", "kind": "clone",
        "settings": settings, "name": "Mine",
    })
    profile = saved["state"]["profiles"][0]
    assert profile["engine"] == "chatterbox"
    assert profile["kind"] == "clone"
    # A clone cannot become Freya's live voice; she speaks with Kokoro.
    assert profile["can_be_freyas_voice"] is False

    spoken = studio.handle({
        "action": "speak", "profile": profile["id"], "text": "Good morning.",
    })
    assert spoken["clip"]["engine"] == "chatterbox"

    json.dumps(spoken)


def test_upload_must_be_real_bytes_from_the_gateway(studio):
    for upload in ("AAAA", [1, 2, 3], None, b""):
        result = studio.handle({
            "action": "reference", "upload": upload, "sample_rate": RATE,
            "consent": True,
        })

        assert result["error"]
        assert result["reference"] is None


def test_designing_a_voice_start_to_finish(studio, references):
    design = {"description": "a calm, low voice", "language": "English"}

    made = studio.handle({
        "action": "design", "engine": "qwen3-tts", "settings": design,
    })
    assert made["error"] is None
    assert made["reference"]["origin"] == "designed"
    assert studio.clips.read(made["clip"]["id"])

    saved = studio.handle({
        "action": "save", "engine": "qwen3-tts", "kind": "design",
        "name": "Calm",
        "settings": {**design, "reference": made["reference"]["id"]},
    })
    profile = saved["state"]["profiles"][0]
    assert saved["error"] is None
    assert profile["settings"]["description"] == "a calm, low voice"

    spoken = studio.handle({
        "action": "speak", "profile": profile["id"], "text": "Hello.",
    })
    assert spoken["clip"]["engine"] == "qwen3-tts"


def test_only_a_design_engine_designs(studio):
    result = studio.handle({
        "action": "design", "engine": "chatterbox",
        "settings": {"description": "calm", "language": "English"},
    })

    assert "cannot design" in result["error"]


def test_a_voice_is_never_used_with_another_engine(studio, references, upload):
    # Chatterbox's clone and Qwen's clone of the same recording are
    # separate voices; and a designed sample cannot be cloned elsewhere.
    made = studio.handle({
        "action": "design", "engine": "qwen3-tts",
        "settings": {"description": "calm", "language": "English"},
    })

    crossed = studio.handle({
        "action": "save", "engine": "chatterbox", "kind": "clone",
        "name": "Crossed",
        "settings": {"reference": made["reference"]["id"]},
    })

    assert crossed["error"]
    assert crossed["state"]["profiles"] == []

    saved = studio.save_profile(
        "Mine", "chatterbox", ROLE_CLONE, {"reference": upload["id"]}
    )
    studio.speak(saved["id"], "Hello.")

    assert studio._engines[0].loaded is True
    assert studio._engines[1].loaded is False


def test_only_one_large_engine_is_loaded_at_a_time(studio, upload):
    chatterbox, qwen = studio._engines
    settings = {"reference": upload["id"]}

    studio.preview("chatterbox", ROLE_CLONE, settings)
    assert (chatterbox.loaded, qwen.loaded) == (True, False)

    studio.preview("qwen3-tts", ROLE_CLONE, settings)
    assert (chatterbox.loaded, qwen.loaded) == (False, True)

    state = studio.handle({"action": "free"})["state"]
    assert (chatterbox.loaded, qwen.loaded) == (False, False)
    assert [engine["loaded"] for engine in state["engines"]] == [False, False]


def test_deleting_a_voice_deletes_its_recording_unless_shared(
    studio, references, upload
):
    settings = {"reference": upload["id"]}
    first = studio.save_profile("One", "chatterbox", ROLE_CLONE, settings)
    second = studio.save_profile("Two", "qwen3-tts", ROLE_CLONE, settings)

    studio.delete_profile(first["id"])
    assert references.get(upload["id"]) is not None

    studio.delete_profile(second["id"])
    assert references.get(upload["id"]) is None
    assert list(references.directory.glob("*.wav")) == []


def test_recordings_no_voice_uses_are_forgotten(studio, references, upload):
    stray = references.add_upload(recording(), RATE, True)
    studio.save_profile(
        "Mine", "chatterbox", ROLE_CLONE, {"reference": upload["id"]}
    )

    studio.forget_unsaved_recordings()

    assert [r["id"] for r in references.list()] == [upload["id"]]
    assert stray["id"] != upload["id"]
