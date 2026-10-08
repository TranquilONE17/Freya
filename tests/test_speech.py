import io
import json

import numpy as np
import pytest
import soundfile as sf

from freya.speech import kokoro_engine
from freya.speech.engines import (
    ROLE_BLEND,
    ROLE_CLONE,
    ROLE_DESIGN,
    ROLE_PRESET,
    STATUS_READY,
    SpeechError,
    planned_engines,
)
from freya.speech.kokoro_engine import LANGUAGES, VOICES, KokoroEngine
from freya.speech.references import ReferenceStore
from freya.speech.store import ClipStore, VoiceProfileStore
from freya.speech.studio import MAX_TEXT_LENGTH, VoiceStudio


PRESET = {"language": "a", "voice": "af_heart", "speed": 1.0}
BLEND = {
    "language": "a",
    "speed": 1.0,
    "voices": [
        {"voice": "af_heart", "weight": 60},
        {"voice": "am_michael", "weight": 40},
    ],
}


class FakePipeline:
    """Stands in for a Kokoro pipeline: records calls, returns a tone."""

    def __init__(self, language):
        self.language = language
        self.calls = []

    def __call__(self, text, voice, speed):
        self.calls.append({"text": text, "voice": voice, "speed": speed})
        yield text, "", np.full(2400, 0.25, dtype=np.float32)
        yield text, "", None
        yield text, "", np.full(2400, -0.25, dtype=np.float32)


@pytest.fixture
def pipelines():
    return {}


@pytest.fixture
def kokoro(pipelines):
    def factory(language):
        pipelines[language] = FakePipeline(language)
        return pipelines[language]

    return KokoroEngine(pipeline_factory=factory)


@pytest.fixture
def live():
    return []


@pytest.fixture
def studio(tmp_path, kokoro, live):
    return VoiceStudio(
        [kokoro] + planned_engines(),
        profiles=VoiceProfileStore(tmp_path / "voice_profiles.json"),
        clips=ClipStore(tmp_path / "clips"),
        apply_live_voice=live.append,
        references=ReferenceStore(tmp_path / "references"),
    )


# -- Kokoro engine -----------------------------------------------------


def test_every_supplied_voice_belongs_to_its_language():
    assert set(VOICES) == set(LANGUAGES)

    for code, voices in VOICES.items():
        assert voices
        assert all(voice[0] == code and voice[1] in "fm" for voice in voices)


def test_kokoro_offers_presets_and_blends_but_not_cloning_or_design(kokoro):
    info = kokoro.info()

    assert info.status == STATUS_READY
    assert info.local is True
    assert set(info.roles) == {ROLE_PRESET, ROLE_BLEND}
    assert info.controls["speed"] == {
        "min": 0.5,
        "max": 2.0,
        "step": 0.05,
        "default": 1.0,
    }
    assert [l["code"] for l in info.controls["languages"]] == list(LANGUAGES)


def test_language_without_its_packages_is_reported_and_refused(
    kokoro, monkeypatch
):
    monkeypatch.setattr(
        kokoro_engine.importlib.util, "find_spec", lambda name: None
    )

    languages = {l["code"]: l for l in kokoro.info().controls["languages"]}

    assert languages["a"]["available"] is True
    assert languages["j"]["available"] is False

    with pytest.raises(SpeechError, match="extra language packages"):
        kokoro.validate(ROLE_PRESET, {"language": "j", "voice": "jf_alpha"})


@pytest.mark.parametrize(
    "settings",
    [
        None,
        "af_heart",
        {},
        {"language": "x", "voice": "af_heart"},
        {"language": "a", "voice": "bf_emma"},
        {"language": "a", "voice": "../secret"},
        {"language": "a", "voice": "af_heart", "speed": 9},
        {"language": "a", "voice": "af_heart", "speed": "fast"},
    ],
)
def test_bad_preset_settings_are_refused(kokoro, settings):
    with pytest.raises(SpeechError):
        kokoro.validate(ROLE_PRESET, settings)


@pytest.mark.parametrize(
    "voices",
    [
        None,
        [],
        [{"voice": "af_heart", "weight": 1}],
        [{"voice": "af_heart", "weight": 1}] * 2,
        [{"voice": "af_heart", "weight": 1}, {"voice": "nobody", "weight": 1}],
        [{"voice": "af_heart", "weight": 0}, {"voice": "af_sky", "weight": 1}],
        [{"voice": "af_heart", "weight": "x"}, {"voice": "af_sky", "weight": 1}],
        ["af_heart", "af_sky"],
        [{"voice": voice, "weight": 1} for voice in VOICES["a"][:5]],
    ],
)
def test_bad_blends_are_refused(kokoro, voices):
    with pytest.raises(SpeechError):
        kokoro.validate(ROLE_BLEND, {"language": "a", "voices": voices})


def test_validate_keeps_only_the_settings_it_understands(kokoro):
    cleaned = kokoro.validate(
        ROLE_PRESET,
        {**PRESET, "speed": "1.234", "reference": "C:/someone.wav"},
    )

    assert cleaned == {"language": "a", "voice": "af_heart", "speed": 1.23}


@pytest.mark.parametrize("kind", [ROLE_CLONE, ROLE_DESIGN, "anything"])
def test_kokoro_refuses_cloning_and_design(kokoro, kind):
    with pytest.raises(SpeechError):
        kokoro.validate(kind, PRESET)


def test_preset_speech_joins_the_pieces_kokoro_returns(kokoro, pipelines):
    audio, rate = kokoro.synthesize("Hello.", ROLE_PRESET, PRESET)

    assert rate == 24000
    assert audio.dtype == np.float32
    assert len(audio) == 4800
    assert pipelines["a"].calls == [
        {"text": "Hello.", "voice": "af_heart", "speed": 1.0}
    ]


def test_blend_is_the_weighted_average_of_supplied_voices(kokoro, pipelines):
    torch = pytest.importorskip("torch")

    packs = {
        "af_heart": torch.full((4, 1, 8), 1.0),
        "am_michael": torch.full((4, 1, 8), 3.0),
    }
    kokoro._pipeline("a").load_single_voice = packs.__getitem__

    kokoro.synthesize("Hello.", ROLE_BLEND, BLEND)
    voice = pipelines["a"].calls[0]["voice"]

    assert voice.shape == (4, 1, 8)
    assert torch.allclose(voice, torch.full((4, 1, 8), 1.8))


def test_unload_drops_the_loaded_pipelines(kokoro, pipelines):
    kokoro.synthesize("Hello.", ROLE_PRESET, PRESET)
    first = pipelines["a"]

    kokoro.unload()
    kokoro.synthesize("Hello.", ROLE_PRESET, PRESET)

    assert pipelines["a"] is not first


# -- engines that are not set up ---------------------------------------


def test_planned_engines_say_what_they_would_do_but_cannot_be_used():
    engines = {engine.id: engine for engine in planned_engines()}

    assert set(engines["chatterbox"].info().roles) == {ROLE_CLONE}
    assert set(engines["qwen3-tts"].info().roles) == {ROLE_DESIGN, ROLE_CLONE}
    assert set(engines["elevenlabs"].info().roles) == {ROLE_CLONE, ROLE_DESIGN}
    assert engines["elevenlabs"].info().local is False

    for engine in engines.values():
        assert engine.info().status != STATUS_READY

        with pytest.raises(SpeechError, match="not set up"):
            engine.synthesize("Hello.", ROLE_CLONE, {})


# -- saved voices ------------------------------------------------------


def test_profiles_survive_a_restart(tmp_path):
    path = tmp_path / "voice_profiles.json"
    store = VoiceProfileStore(path)
    saved = store.add("  Warm   voice ", "kokoro", ROLE_PRESET, PRESET)
    store.set_active(saved["id"])

    again = VoiceProfileStore(path)

    assert again.list() == [saved]
    assert saved["name"] == "Warm voice"
    assert again.active_id == saved["id"]


def test_profile_names_must_be_given_short_and_unique(tmp_path):
    store = VoiceProfileStore(tmp_path / "voice_profiles.json")
    store.add("Warm", "kokoro", ROLE_PRESET, PRESET)

    for name in ("", "   ", None, "x" * 41, "warm"):
        with pytest.raises(SpeechError):
            store.add(name, "kokoro", ROLE_PRESET, PRESET)

    assert len(store.list()) == 1


def test_deleting_the_active_profile_clears_it(tmp_path):
    store = VoiceProfileStore(tmp_path / "voice_profiles.json")
    saved = store.add("Warm", "kokoro", ROLE_PRESET, PRESET)
    store.set_active(saved["id"])

    assert store.delete(saved["id"]) is True
    assert store.delete(saved["id"]) is False
    assert store.active_id is None

    with pytest.raises(SpeechError):
        store.set_active(saved["id"])


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        json.dumps({"profiles": "none", "active": 3}),
        json.dumps(
            {
                "profiles": [
                    {"id": "../x", "name": "a", "engine": "kokoro",
                     "kind": "preset", "settings": {}},
                    {"id": "0" * 32, "name": "a", "engine": "kokoro",
                     "kind": "stolen", "settings": {}},
                    "junk",
                ],
                "active": "0" * 32,
            }
        ),
    ],
)
def test_damaged_profile_file_is_ignored(tmp_path, content):
    path = tmp_path / "voice_profiles.json"
    path.write_text(content, encoding="utf-8")

    store = VoiceProfileStore(path)

    assert store.list() == []
    assert store.active_id is None


# -- generated clips ---------------------------------------------------


def test_clip_is_a_playable_wav(tmp_path):
    clips = ClipStore(tmp_path / "clips")
    clip = clips.add(np.zeros(12000, dtype=np.float32), 24000, "kokoro", "Hi")

    audio, rate = sf.read(io.BytesIO(clips.read(clip["id"])))

    assert clip["seconds"] == 0.5
    assert rate == 24000
    assert len(audio) == 12000


def test_only_clips_the_store_made_can_be_read(tmp_path):
    clips = ClipStore(tmp_path / "clips")
    clips.add(np.zeros(10, dtype=np.float32), 24000, "kokoro", "Hi")
    stray = "a" * 32
    (tmp_path / "clips" / f"{stray}.wav").write_bytes(b"RIFF")
    (tmp_path / "secret.wav").write_bytes(b"RIFF")

    for asked in (stray, "../secret", "..\\secret", "", None, 5, "A" * 32):
        assert clips.read(asked) is None


def test_old_clips_are_removed_and_clear_removes_the_rest(tmp_path):
    clips = ClipStore(tmp_path / "clips", limit=2)
    made = [
        clips.add(np.zeros(10, dtype=np.float32), 24000, "kokoro", str(n))
        for n in range(3)
    ]

    assert clips.read(made[0]["id"]) is None
    assert clips.read(made[2]["id"]) is not None
    assert len(list((tmp_path / "clips").glob("*.wav"))) == 2

    clips.clear()

    assert list((tmp_path / "clips").glob("*.wav")) == []
    assert clips.read(made[2]["id"]) is None


# -- the studio --------------------------------------------------------


def test_each_section_lists_only_engines_that_do_that_work(studio):
    state = studio.describe()

    assert state["sections"] == {
        "clone": ["chatterbox", "qwen3-tts", "elevenlabs"],
        "design": ["qwen3-tts", "elevenlabs"],
        "preset": ["kokoro"],
        "blend": ["kokoro"],
        "playground": ["kokoro"],
    }
    assert state["profiles"] == []
    assert state["active_profile"] is None
    json.dumps(state)


def test_preview_returns_a_clip_without_saving_anything(studio, pipelines):
    clip = studio.preview("kokoro", ROLE_PRESET, PRESET)

    assert studio.clips.read(clip["id"])
    assert clip["engine"] == "kokoro"
    assert pipelines["a"].calls[0]["text"].startswith("Hello.")
    assert studio.profiles.list() == []


@pytest.mark.parametrize(
    "engine, kind",
    [
        ("kokoro", ROLE_CLONE),
        ("kokoro", ROLE_DESIGN),
        ("chatterbox", ROLE_CLONE),
        ("elevenlabs", ROLE_DESIGN),
        ("unknown", ROLE_PRESET),
        (None, None),
    ],
)
def test_work_an_engine_cannot_do_is_refused(studio, engine, kind):
    with pytest.raises(SpeechError):
        studio.preview(engine, kind, PRESET)

    with pytest.raises(SpeechError):
        studio.save_profile("Voice", engine, kind, PRESET)

    assert studio.profiles.list() == []


@pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_TEXT_LENGTH + 1)])
def test_empty_or_overlong_text_is_refused(studio, text):
    saved = studio.save_profile("Warm", "kokoro", ROLE_PRESET, PRESET)

    with pytest.raises(SpeechError):
        studio.speak(saved["id"], text)


def test_saved_voice_speaks_through_its_own_engine(studio, pipelines):
    saved = studio.save_profile("Brit", "kokoro", ROLE_PRESET, {
        "language": "b", "voice": "bf_emma", "speed": 1.2,
    })

    clip = studio.speak(saved["id"], "Good  morning.")

    assert clip["label"] == "Good morning."
    assert pipelines["b"].calls == [
        {"text": "Good morning.", "voice": "bf_emma", "speed": 1.2}
    ]


def test_profile_of_an_engine_that_is_not_ready_cannot_speak(studio):
    # A clone made with Chatterbox means nothing to Kokoro, so it is
    # never handed to it, even though Kokoro is the engine that works.
    saved = studio.profiles.add(
        "Clone", "chatterbox", ROLE_CLONE, {"reference": "abc"}
    )

    with pytest.raises(SpeechError, match="Chatterbox is not set up"):
        studio.speak(saved["id"], "Hello.")

    assert studio.describe()["profiles"][0]["can_be_freyas_voice"] is False

    with pytest.raises(SpeechError):
        studio.use_profile(saved["id"])


def test_english_kokoro_voice_can_become_freyas_voice(studio, live):
    saved = studio.save_profile("Warm", "kokoro", ROLE_BLEND, BLEND)

    studio.use_profile(saved["id"])

    assert live == [saved]
    assert studio.describe()["active_profile"] == saved["id"]

    studio.use_profile(None)

    assert live == [saved, None]
    assert studio.describe()["active_profile"] is None


def test_other_languages_cannot_become_freyas_voice(studio, live):
    saved = studio.save_profile("Dora", "kokoro", ROLE_PRESET, {
        "language": "e", "voice": "ef_dora",
    })

    with pytest.raises(SpeechError, match="English"):
        studio.use_profile(saved["id"])

    assert live == []
    assert studio.describe()["profiles"][0]["can_be_freyas_voice"] is False


def test_deleting_freyas_voice_returns_her_to_the_default(studio, live):
    saved = studio.save_profile("Warm", "kokoro", ROLE_PRESET, PRESET)
    studio.use_profile(saved["id"])

    studio.delete_profile(saved["id"])

    assert live == [saved, None]

    with pytest.raises(SpeechError):
        studio.delete_profile(saved["id"])


def test_chosen_voice_is_restored_at_start_up(tmp_path, kokoro):
    path = tmp_path / "voice_profiles.json"
    references = ReferenceStore(tmp_path / "references")
    first = VoiceStudio(
        [kokoro],
        VoiceProfileStore(path),
        ClipStore(tmp_path),
        references=references,
    )
    saved = first.save_profile("Warm", "kokoro", ROLE_PRESET, PRESET)
    first.use_profile(saved["id"])

    live = []
    again = VoiceStudio(
        [kokoro],
        VoiceProfileStore(path),
        ClipStore(tmp_path),
        apply_live_voice=live.append,
        references=references,
    )
    again.restore_live_voice()

    assert live == [saved]


# -- requests from the window ------------------------------------------


def test_window_can_preview_save_use_speak_and_delete(studio, live):
    preview = studio.handle({
        "action": "preview", "engine": "kokoro", "kind": "preset",
        "settings": PRESET,
    })
    assert preview["error"] is None
    assert studio.clips.read(preview["clip"]["id"])

    saved = studio.handle({
        "action": "save", "engine": "kokoro", "kind": "preset",
        "settings": PRESET, "name": "Warm",
    })
    profile = saved["state"]["profiles"][0]
    assert saved["error"] is None and saved["clip"] is None
    assert profile["name"] == "Warm"

    used = studio.handle({"action": "use", "profile": profile["id"]})
    assert used["state"]["active_profile"] == profile["id"]

    spoken = studio.handle({
        "action": "speak", "profile": profile["id"], "text": "Hello.",
    })
    assert spoken["clip"]["label"] == "Hello."

    deleted = studio.handle({"action": "delete", "profile": profile["id"]})
    assert deleted["state"]["profiles"] == []
    assert live[-1] is None


@pytest.mark.parametrize(
    "message",
    [
        {},
        {"action": "format-disk"},
        {"action": "preview"},
        {"action": "preview", "engine": "kokoro", "kind": "preset",
         "settings": ["af_heart"]},
        {"action": "preview", "engine": "kokoro", "kind": "preset",
         "settings": PRESET, "text": "x" * 5000},
        {"action": "save", "engine": "kokoro", "kind": "preset",
         "settings": PRESET},
        {"action": "speak", "profile": {"id": 1}, "text": "Hello."},
        {"action": "use", "profile": "nothing"},
        {"action": "delete", "profile": ["a"]},
    ],
)
def test_bad_window_requests_report_an_error_and_change_nothing(
    studio, live, message
):
    result = studio.handle(message)

    assert result["error"]
    assert result["clip"] is None
    assert result["state"]["profiles"] == []
    assert live == []


def test_an_engine_failure_is_reported_not_raised(studio, kokoro, monkeypatch):
    def broken(text, kind, settings):
        raise RuntimeError("model fell over")

    monkeypatch.setattr(kokoro, "synthesize", broken)

    result = studio.handle({
        "action": "preview", "engine": "kokoro", "kind": "preset",
        "settings": PRESET,
    })

    assert "model fell over" in result["error"]
    assert result["clip"] is None
