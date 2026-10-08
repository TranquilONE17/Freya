import json
import os
import threading
import zipfile
from importlib import resources
from pathlib import Path

import pytest

from freya.control_plane import build_local_control_plane
from freya.spatial_avatar import converter as converter_module
from freya.spatial_avatar.config import AvatarConfigStore
from freya.spatial_avatar.converter import (
    AvatarConverter,
    ConversionError,
    find_blender,
    plan,
    slug,
    unpack,
)
from freya.spatial_avatar.geometry import single_display_layout
from freya.spatial_avatar.host import AvatarHost
from freya.spatial_avatar.library import AvatarLibrary
from freya.spatial_avatar.service import (
    AVATAR_CAPABILITIES,
    AVATAR_PREPARE,
    AVATAR_SEARCH,
    AvatarService,
)
from freya.spatial_avatar.sources import (
    ARCHIVE,
    CONVERTIBLE,
    READY,
    UNSUITABLE,
    SourceSearch,
    best_inside,
    classify,
)
from test_avatar_library import vrm1


def make_zip(path, names):
    with zipfile.ZipFile(path, "w") as bundle:
        for name, content in names.items():
            bundle.writestr(name, content)

    return path


@pytest.fixture
def downloads(tmp_path):
    folder = tmp_path / "downloads"
    folder.mkdir()

    return folder


# -- what a file is -------------------------------------------------------


def test_files_are_sorted_by_what_can_be_done_with_them(downloads):
    (downloads / "ready.vrm").write_bytes(b"x" * 10)
    (downloads / "girl.blend").write_bytes(b"x" * 10)
    (downloads / "statue.stl").write_bytes(b"x" * 10)
    (downloads / "notes.txt").write_text("hello")
    make_zip(downloads / "pack.zip", {"a/Girl_Rig.blend": "x", "a/tex.png": "x"})
    make_zip(downloads / "prints.zip", {"statue.stl": "x"})
    make_zip(downloads / "photos.zip", {"one.jpg": "x"})

    assert classify(downloads / "ready.vrm")["status"] == READY
    assert classify(downloads / "girl.blend")["status"] == CONVERTIBLE
    assert classify(downloads / "statue.stl")["status"] == UNSUITABLE
    assert classify(downloads / "notes.txt") is None
    assert classify(downloads / "photos.zip") is None
    assert classify(downloads / "prints.zip")["status"] == UNSUITABLE

    pack = classify(downloads / "pack.zip")
    assert pack["status"] == ARCHIVE
    assert pack["inside"] == ["a/Girl_Rig.blend"]


def test_damaged_archive_is_passed_over(downloads):
    (downloads / "broken.zip").write_bytes(b"this is not a zip")

    assert classify(downloads / "broken.zip") is None


def test_the_rigged_file_in_an_archive_is_tried_first():
    names = [
        "pack/Girl_No_Rig.blend",
        "pack/Girl_Pose_Rig.blend",
        "pack/Girl_Rig.blend",
        "pack/readme.txt",
        "pack/Girl.vrm",
    ]

    assert best_inside(names) == [
        "pack/Girl.vrm",
        "pack/Girl_Rig.blend",
        "pack/Girl_Pose_Rig.blend",
        "pack/Girl_No_Rig.blend",
    ]


def test_search_looks_a_little_way_down_and_skips_the_avatar_folder(downloads, tmp_path):
    (downloads / "top.vrm").write_bytes(b"x")
    (downloads / "one" / "two").mkdir(parents=True)
    (downloads / "one" / "two" / "deep.fbx").write_bytes(b"x")
    (downloads / "one" / "two" / "three").mkdir()
    (downloads / "one" / "two" / "three" / "too_deep.fbx").write_bytes(b"x")
    (downloads / "mine").mkdir()
    (downloads / "mine" / "already.vrm").write_bytes(b"x")

    search = SourceSearch([downloads, tmp_path / "missing"], skip=[downloads / "mine"])
    found = search.search()

    assert [entry["name"] for entry in found] == ["top.vrm", "deep.fbx"]
    assert found[0]["status"] == READY


def test_only_a_found_file_can_be_asked_for(downloads):
    (downloads / "top.vrm").write_bytes(b"x")
    search = SourceSearch([downloads])
    entry = search.search()[0]

    assert search.path(entry["id"]) == downloads / "top.vrm"
    assert search.path("0" * 24) is None
    assert search.path(str(downloads / "top.vrm")) is None
    assert search.path(None) is None
    assert search.path({"id": entry["id"]}) is None

    (downloads / "top.vrm").unlink()
    assert search.path(entry["id"]) is None


# -- unpacking ---------------------------------------------------------------


def test_unpack_returns_the_files(downloads, tmp_path):
    archive = make_zip(downloads / "pack.zip", {"a/one.blend": "x", "a/b/two.png": "y"})

    files = unpack(archive, tmp_path / "out")

    assert sorted(path.name for path in files) == ["one.blend", "two.png"]


def test_archive_that_writes_outside_its_folder_is_refused(downloads, tmp_path):
    archive = make_zip(downloads / "bad.zip", {"../escaped.txt": "x", "ok.blend": "x"})

    with pytest.raises(ConversionError, match="outside"):
        unpack(archive, tmp_path / "out")

    assert not (tmp_path / "escaped.txt").exists()
    assert list((tmp_path / "out").iterdir()) == []


def test_oversized_archive_is_refused_before_unpacking(downloads, tmp_path, monkeypatch):
    archive = make_zip(downloads / "big.zip", {"a.blend": "x" * 5000})
    monkeypatch.setattr(converter_module, "MAX_UNPACKED_BYTES", 1000)

    with pytest.raises(ConversionError, match="too large"):
        unpack(archive, tmp_path / "out")

    assert list((tmp_path / "out").iterdir()) == []


def test_archive_with_too_many_files_is_refused(downloads, tmp_path, monkeypatch):
    archive = make_zip(downloads / "many.zip", {f"{n}.txt": "x" for n in range(6)})
    monkeypatch.setattr(converter_module, "MAX_UNPACKED_FILES", 5)

    with pytest.raises(ConversionError, match="too many"):
        unpack(archive, tmp_path / "out")


# -- deciding what a model needs ------------------------------------------------


def test_plan_explains_what_will_be_done():
    decision = plan(
        {"ok": True, "rig": "rig", "rig_kind": "auto-rig-pro", "rig_bones": 700,
         "height": 17.2, "face_shapes": 52, "embedded_scripts": ["rig_ui.py"]}
    )
    text = " ".join(decision["notes"])

    assert decision["possible"]
    assert "700 bones" in text
    assert "resize" in text
    assert "52 face shapes" in text
    assert "does not run them" in text


def test_plan_refuses_a_model_with_no_skeleton():
    decision = plan({"ok": True, "rig": None, "face_shapes": 0})

    assert not decision["possible"]
    assert "no skeleton" in decision["notes"][0]


def test_plan_passes_on_why_a_file_could_not_be_opened():
    decision = plan({"ok": False, "problems": ["The file could not be opened: bad"]})

    assert not decision["possible"]
    assert decision["notes"] == ["The file could not be opened: bad"]


def test_plan_warns_about_missing_face_shapes():
    none = plan({"ok": True, "rig": "Armature", "rig_kind": "plain", "height": 1.7, "face_shapes": 0})
    few = plan({"ok": True, "rig": "Armature", "rig_kind": "plain", "height": 1.7, "face_shapes": 9})

    assert none["possible"] and "no expressions" in " ".join(none["notes"])
    assert few["possible"] and "only 9" in " ".join(few["notes"])
    assert "resize" not in " ".join(few["notes"])


def test_names_become_safe_file_names():
    assert slug("Stylized Girl (Rig) 3.6!") == "stylized-girl-rig-3-6"
    assert slug("../../evil") == "evil"
    assert slug("***") == "avatar"
    assert len(slug("x" * 200)) == 48


# -- finding Blender ---------------------------------------------------------------


def test_blender_is_found_by_setting_or_in_the_usual_place(tmp_path, monkeypatch):
    named = tmp_path / "custom" / "blender.exe"
    named.parent.mkdir()
    named.write_bytes(b"")

    monkeypatch.setenv("FREYA_BLENDER", str(named))
    assert find_blender() == named

    monkeypatch.setenv("FREYA_BLENDER", str(tmp_path / "nowhere.exe"))
    assert find_blender() is None

    monkeypatch.delenv("FREYA_BLENDER")
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert find_blender() is None

    for version in ("4.2", "5.2"):
        folder = tmp_path / "Blender Foundation" / f"Blender {version}"
        folder.mkdir(parents=True)
        (folder / "blender.exe").write_bytes(b"")

    assert find_blender().parent.name == "Blender 5.2"


def test_blender_is_started_without_scripts_from_the_model(tmp_path, monkeypatch):
    calls = []

    class Process:
        pid = 0

        def wait(self, timeout=None):
            return 0

    def popen(command, **options):
        calls.append((command, options))
        return Process()

    monkeypatch.setattr(converter_module.subprocess, "Popen", popen)

    converter_module.run_blender(
        Path("blender.exe"), "inspect_model.py", {"source": "x"}, 5, tmp_path / "log.txt"
    )

    command = calls[0][0]
    assert "--background" in command
    assert "--disable-autoexec" in command
    assert command[command.index("--python") + 1].endswith("inspect_model.py")
    assert "--enable-autoexec" not in command
    # The request file is removed afterwards.
    assert not Path(command[-1]).exists()


def test_the_blender_scripts_never_switch_model_scripts_on():
    folder = resources.files("freya.spatial_avatar") / "blender"

    for name in ("inspect_model.py", "convert_model.py"):
        text = (folder / name).read_text(encoding="utf-8")

        assert "use_scripts=False" in text, name
        assert "use_scripts=True" not in text, name
        assert "use_scripts_auto_execute" not in text, name
        assert "exec(" not in text and "eval(" not in text, name


# -- making a file ready ------------------------------------------------------------


class FakeBlender:
    """
    Stands in for Blender: writes the report or the avatar file that
    the real scripts would, and remembers what it was asked.
    """

    def __init__(self, reports=None, fail_convert=False):
        self.reports = reports or {}
        self.fail_convert = fail_convert
        self.calls = []

    def __call__(self, blender, script, request, timeout, log, started=None):
        self.calls.append((script, dict(request)))

        if script == "inspect_model.py":
            name = Path(request["source"]).name
            report = self.reports.get(
                name,
                {"ok": True, "rig": "rig", "rig_kind": "auto-rig-pro", "rig_bones": 600,
                 "height": 1.7, "face_shapes": 52, "face_shape_names": ["jawOpen"]},
            )
            Path(request["report"]).write_text(json.dumps(report), encoding="utf-8")
        elif self.fail_convert:
            Path(request["result"]).write_text(
                json.dumps({"ok": False, "warnings": [],
                            "steps": [{"step": "say which bone is which", "ok": False,
                                       "error": "no bone could be found for: hips"}]}),
                encoding="utf-8",
            )
        else:
            Path(request["output"]).write_bytes(vrm1())
            Path(request["result"]).write_text(
                json.dumps({"ok": True, "steps": [], "warnings": ["Hair was joined."]}),
                encoding="utf-8",
            )


@pytest.fixture
def models(tmp_path):
    return tmp_path / "avatar_models"


def make_converter(models, tmp_path, run):
    return AvatarConverter(models, tmp_path / "work", blender=Path("blender.exe"), run=run)


def test_a_vrm_only_needs_copying(downloads, models, tmp_path):
    source = downloads / "Nice Avatar.vrm"
    source.write_bytes(vrm1())
    blender = FakeBlender()

    done = make_converter(models, tmp_path, blender).prepare(source)

    assert done["file"] == "nice-avatar.vrm"
    assert (models / "nice-avatar.vrm").read_bytes() == source.read_bytes()
    assert blender.calls == []
    assert source.exists()


def test_a_character_file_is_inspected_then_converted(downloads, models, tmp_path):
    source = downloads / "girl.blend"
    source.write_bytes(b"blend")
    blender = FakeBlender()
    said = []

    done = make_converter(models, tmp_path, blender).prepare(
        source, name="My Girl", author="Somebody", progress=said.append
    )

    assert [script for script, _ in blender.calls] == ["inspect_model.py", "convert_model.py"]
    request = blender.calls[1][1]
    assert request["rig"] == "rig" and request["rig_kind"] == "auto-rig-pro"
    assert request["name"] == "My Girl" and request["author"] == "Somebody"
    assert request["face_units"] == ["jawOpen"]
    assert Path(request["output"]) == models / "my-girl.vrm"
    assert "not for redistribution" in request["copyright"]

    assert done["file"] == "my-girl.vrm"
    assert "Hair was joined." in done["notes"]
    assert any("Converting" in text for text in said)
    # The original is untouched and nothing is left in the work folder.
    assert source.read_bytes() == b"blend"
    assert [p for p in (tmp_path / "work").iterdir() if p.is_dir()] == []


def test_an_existing_avatar_is_never_overwritten(downloads, models, tmp_path):
    source = downloads / "girl.blend"
    source.write_bytes(b"blend")
    converter = make_converter(models, tmp_path, FakeBlender())

    assert converter.prepare(source)["file"] == "girl.vrm"
    assert converter.prepare(source)["file"] == "girl-2.vrm"


def test_an_archive_is_unpacked_and_its_rigged_file_used(downloads, models, tmp_path):
    archive = make_zip(
        downloads / "pack.zip",
        {"p/Girl_No_Rig.blend": "a", "p/Girl_Rig.blend": "b", "p/skin.png": "c"},
    )
    blender = FakeBlender()

    done = make_converter(models, tmp_path, blender).prepare(archive)

    assert Path(blender.calls[0][1]["source"]).name == "Girl_Rig.blend"
    assert done["source"] == "Girl_Rig.blend"
    assert (models / done["file"]).is_file()


def test_the_next_file_is_tried_when_one_has_no_skeleton(downloads, models, tmp_path):
    archive = make_zip(downloads / "pack.zip", {"A_Rig.blend": "a", "B_Rig_x.blend": "b"})
    blender = FakeBlender(reports={"A_Rig.blend": {"ok": True, "rig": None}})

    done = make_converter(models, tmp_path, blender).prepare(archive)

    assert done["source"] == "B_Rig_x.blend"


def test_a_model_with_no_skeleton_is_refused_with_the_reason(downloads, models, tmp_path):
    source = downloads / "statue.fbx"
    source.write_bytes(b"x")
    blender = FakeBlender(reports={"statue.fbx": {"ok": True, "rig": None}})

    with pytest.raises(ConversionError, match="no skeleton"):
        make_converter(models, tmp_path, blender).prepare(source)

    assert not models.exists() or list(models.iterdir()) == []


def test_a_failed_conversion_leaves_nothing_behind(downloads, models, tmp_path):
    source = downloads / "girl.blend"
    source.write_bytes(b"x")
    blender = FakeBlender(fail_convert=True)

    with pytest.raises(ConversionError, match="hips"):
        make_converter(models, tmp_path, blender).prepare(source)

    assert list(models.iterdir()) == []


def test_blender_missing_is_said_plainly(downloads, models, tmp_path, monkeypatch):
    source = downloads / "girl.blend"
    source.write_bytes(b"x")
    monkeypatch.setattr(converter_module, "find_blender", lambda: None)
    converter = AvatarConverter(models, tmp_path / "work", run=FakeBlender())

    with pytest.raises(ConversionError, match="not installed"):
        converter.prepare(source)


def test_blender_writing_no_report_is_an_error_not_a_crash(downloads, models, tmp_path):
    source = downloads / "girl.blend"
    source.write_bytes(b"x")

    def silent(blender, script, request, timeout, log, started=None):
        pass

    with pytest.raises(ConversionError, match="could not read"):
        make_converter(models, tmp_path, silent).prepare(source)


# -- through the broker, and from the window ----------------------------------


@pytest.fixture
def plane(tmp_path, fake_ollama):
    plane = build_local_control_plane(tmp_path / "control.db", None)
    yield plane
    plane.close()


@pytest.fixture
def blender():
    return FakeBlender()


@pytest.fixture
def service(plane, downloads, models, blender, tmp_path):
    events = []
    models.mkdir()
    library = AvatarLibrary(models, tmp_path / "avatar_library.json")
    service = AvatarService(
        plane.broker,
        "local-owner",
        store=AvatarConfigStore(tmp_path / "avatar.json"),
        host=AvatarHost("null", log_path=tmp_path / "overlay.log"),
        probe=single_display_layout,
        library=library,
        search=SourceSearch([downloads], skip=[models]),
        converter=make_converter(models, tmp_path, blender),
        publish=lambda kind, **fields: events.append((kind, fields)),
    )
    service.events = events
    plane.register_avatar(service)
    yield service
    service.stop()


def wait_for_job(service):
    service._job_thread.join(timeout=20)
    assert not service._job_thread.is_alive()

    return service.describe()["creator"]["job"]


def test_search_and_prepare_are_separate_audited_permissions(plane, service, downloads):
    (downloads / "girl.blend").write_bytes(b"x")

    assert AVATAR_SEARCH in AVATAR_CAPABILITIES and AVATAR_PREPARE in AVATAR_CAPABILITIES
    assert plane.broker.exists(AVATAR_SEARCH) and plane.broker.exists(AVATAR_PREPARE)
    # Nothing is looked for until a search is asked for.
    assert service.describe()["creator"]["sources"] is None

    answer = service.handle({"action": "search"})
    assert answer["error"] is None
    sources = answer["state"]["creator"]["sources"]
    assert [s["name"] for s in sources] == ["girl.blend"]

    rules = {rule["capability"]: rule["rule_id"] for rule in plane.policy.list_rules()}
    plane.policy.remove_rule(rules[AVATAR_PREPARE])

    refused = service.handle({"action": "prepare", "value": {"source": sources[0]["id"]}})
    assert "not authorized" in refused["error"].lower()
    assert service.handle({"action": "search"})["error"] is None

    rows = plane.store.execute(
        "SELECT outcome FROM audit_event WHERE capability = ?", (AVATAR_SEARCH,)
    ).fetchall()
    assert ("succeeded",) in [tuple(row) for row in rows]


def test_preparing_from_the_window_ends_with_a_model_in_the_library(service, downloads, blender):
    (downloads / "girl.blend").write_bytes(b"x")
    source = service.handle({"action": "search"})["state"]["creator"]["sources"][0]

    answer = service.handle(
        {"action": "prepare", "value": {"source": source["id"], "author": "  Some Artist  "}}
    )
    assert answer["error"] is None

    job = wait_for_job(service)
    assert job["running"] is False and job["error"] == ""
    assert job["file"] == "girl.vrm"
    assert blender.calls[1][1]["author"] == "Some Artist"

    state = service.describe()
    assert [m["file_name"] for m in state["library"]["models"]] == ["girl.vrm"]
    # The window was told as the work went on.
    assert any(kind == "avatar" for kind, _ in service.events)


def test_only_a_file_the_search_found_can_be_prepared(service, downloads, tmp_path):
    (downloads / "statue.stl").write_bytes(b"x")
    elsewhere = tmp_path / "elsewhere.blend"
    elsewhere.write_bytes(b"x")

    # Before any search, nothing can be named.
    assert "last search" in service.handle(
        {"action": "prepare", "value": {"source": str(elsewhere)}}
    )["error"]

    statue = service.handle({"action": "search"})["state"]["creator"]["sources"][0]

    for value in ({"source": str(elsewhere)}, {"source": "../x"}, {}, None, "text"):
        answer = service.handle({"action": "prepare", "value": value})
        assert "last search" in answer["error"], value

    answer = service.handle({"action": "prepare", "value": {"source": statue["id"]}})
    assert "cannot become an avatar" in answer["error"]


def test_one_conversion_at_a_time(service, downloads, blender):
    (downloads / "girl.blend").write_bytes(b"x")
    source = service.handle({"action": "search"})["state"]["creator"]["sources"][0]
    release = threading.Event()

    def slow(*args, **kwargs):
        release.wait(timeout=20)
        return FakeBlender.__call__(blender, *args, **kwargs)

    service._converter._run = slow

    assert service.handle({"action": "prepare", "value": {"source": source["id"]}})["error"] is None
    second = service.handle({"action": "prepare", "value": {"source": source["id"]}})
    assert "already preparing" in second["error"]

    release.set()
    assert wait_for_job(service)["file"] == "girl.vrm"


def test_a_failure_is_reported_and_freya_carries_on(service, downloads, blender):
    (downloads / "girl.blend").write_bytes(b"x")
    blender.fail_convert = True
    source = service.handle({"action": "search"})["state"]["creator"]["sources"][0]

    service.handle({"action": "prepare", "value": {"source": source["id"]}})
    job = wait_for_job(service)

    assert job["running"] is False
    assert "hips" in job["error"]
    assert service.handle({"action": "show"})["error"] is None


def test_the_page_has_the_search_and_the_expression_tester():
    static = resources.files("freya.gateway") / "static"
    page = (static / "index.html").read_text(encoding="utf-8")
    script = (static / "app.js").read_text(encoding="utf-8")
    viewer = (static / "avatar-view.js").read_text(encoding="utf-8")

    for control in ('id="creator-search"', 'id="creator-sources"', 'id="creator-job"',
                    'id="preview-expressions"', 'id="preview-shapes"',
                    'id="preview-strength"', 'id="preview-view-face"', 'id="preview-reset"'):
        assert control in page, control

    for name in ("setExpression", "resetExpressions", "setView"):
        assert name in viewer and name in script, name

    # The page says that the original file is left alone.
    assert "never changes the original" in page
