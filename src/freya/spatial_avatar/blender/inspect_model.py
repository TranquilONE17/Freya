"""
Runs inside Blender. Reports what a 3D model file contains, so Freya can
decide whether and how it can become an avatar.

    blender -b --disable-autoexec --python inspect_model.py -- <request.json>

The request names the model file and where to write the report. A .blend
file is opened; other formats are imported. Nothing is saved and nothing in
the model is changed. Scripts embedded in the file are not run: Blender is
started with them disabled, and this script never enables them.
"""
import json
import sys
import traceback
from pathlib import Path

import bpy

request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
source = Path(request["source"])
report = {"source": source.name, "ok": False, "problems": []}

ARKIT = (
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "eyeBlinkLeft", "eyeBlinkRight",
    "eyeLookDownLeft", "eyeLookDownRight", "eyeLookInLeft", "eyeLookInRight",
    "eyeLookOutLeft", "eyeLookOutRight", "eyeLookUpLeft", "eyeLookUpRight",
    "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight", "jawForward",
    "jawLeft", "jawOpen", "jawRight", "mouthClose", "mouthDimpleLeft", "mouthDimpleRight",
    "mouthFrownLeft", "mouthFrownRight", "mouthFunnel", "mouthLeft", "mouthLowerDownLeft",
    "mouthLowerDownRight", "mouthPressLeft", "mouthPressRight", "mouthPucker", "mouthRight",
    "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
    "mouthSmileLeft", "mouthSmileRight", "mouthStretchLeft", "mouthStretchRight",
    "mouthUpperUpLeft", "mouthUpperUpRight", "noseSneerLeft", "noseSneerRight", "tongueOut",
)


def load():
    kind = source.suffix.lower()

    if kind == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
    else:
        for obj in list(bpy.data.objects):
            bpy.data.objects.remove(obj, do_unlink=True)

        if kind == ".fbx":
            bpy.ops.import_scene.fbx(filepath=str(source))
        elif kind in (".glb", ".gltf"):
            bpy.ops.import_scene.gltf(filepath=str(source))
        else:
            raise ValueError(f"Freya cannot read {kind} files as characters.")


def rig_kind(armature) -> str:
    names = set(armature.data.bones.keys())

    if "c_pos" in names or any(name.startswith("c_root_master") for name in names):
        return "auto-rig-pro"

    if "rig_id" in armature.data.keys() or any(name.startswith(("ORG-", "MCH-")) for name in names):
        return "rigify"

    if any(name.lower().startswith("mixamorig") for name in names):
        return "mixamo"

    return "plain"


def describe():
    meshes = [
        obj for obj in bpy.data.objects
        if obj.type == "MESH" and len(obj.data.polygons) > 0
    ]
    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    skinned = [
        obj for obj in meshes
        if any(modifier.type == "ARMATURE" and modifier.object for modifier in obj.modifiers)
    ]

    # The skeleton that actually moves the most of the character.
    use = {}
    for obj in skinned:
        for modifier in obj.modifiers:
            if modifier.type == "ARMATURE" and modifier.object:
                use[modifier.object.name] = use.get(modifier.object.name, 0) + len(obj.data.vertices)

    main = bpy.data.objects[max(use, key=use.get)] if use else None
    character = [
        obj for obj in skinned
        if main is not None
        and any(m.type == "ARMATURE" and m.object == main for m in obj.modifiers)
    ]

    shapes = set()
    for obj in character:
        if obj.data.shape_keys is not None:
            shapes.update(block.name for block in obj.data.shape_keys.key_blocks)

    top = max(
        ((obj.matrix_world @ vertex.co).z for obj in character for vertex in obj.data.vertices),
        default=0.0,
    )
    bottom = min(
        ((obj.matrix_world @ vertex.co).z for obj in character for vertex in obj.data.vertices),
        default=0.0,
    )

    report.update(
        {
            "meshes": len(meshes),
            "triangles": sum(
                sum(len(polygon.vertices) - 2 for polygon in obj.data.polygons)
                for obj in (character or meshes)
            ),
            "armatures": [obj.name for obj in armatures],
            "rig": main.name if main else None,
            "rig_kind": rig_kind(main) if main else None,
            "rig_bones": len(main.data.bones) if main else 0,
            "character_meshes": [obj.name for obj in character],
            "height": round(top - bottom, 4),
            "face_shapes": len([name for name in ARKIT if name in shapes]),
            "face_shape_names": [name for name in ARKIT if name in shapes],
            "all_shapes": len(shapes),
            "embedded_scripts": [text.name for text in bpy.data.texts][:20],
        }
    )

    if not meshes:
        report["problems"].append("The file has no 3D surface in it.")
    elif main is None:
        report["problems"].append(
            "The model has no skeleton, so it cannot move. Giving it one is "
            "modelling work Freya does not do."
        )

    if main is not None and report["face_shapes"] == 0:
        report["problems"].append(
            "The model has no standard face shapes, so it will have no "
            "expressions or lip movement."
        )


try:
    load()
    describe()
    report["ok"] = True
except Exception as exc:
    report["problems"].append(f"The file could not be opened: {exc}")
    traceback.print_exc()

Path(request["report"]).write_text(json.dumps(report, indent=1), encoding="utf-8")
print("INSPECTION WRITTEN", flush=True)
