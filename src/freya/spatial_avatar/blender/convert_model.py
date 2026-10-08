"""
Runs inside Blender. Turns a rigged character into a VRM avatar.

    blender -b --disable-autoexec --python convert_model.py -- <request.json>

The request names the model file, the kind of skeleton it has (as found by
inspect_model.py), and where to write the avatar. The original file is never
saved. The character keeps its own surface, pictures, and face shapes. What
changes:

  - an animation rig with hundreds of helper bones is replaced by the plain
    humanoid skeleton a VRM needs, and every point of the surface is re-attached
    to it;
  - it is resized to metres;
  - its materials are reduced to the simple kind every viewer understands;
  - its face shapes are offered as VRM expressions.

Scripts embedded in the model are not run.
"""
import json
import re
import sys
import traceback
from collections import defaultdict
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

request = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
source = Path(request["source"])
output = Path(request["output"])
result = {"ok": False, "steps": [], "warnings": []}


def step(label, action):
    try:
        value = action()
        result["steps"].append({"step": label, "ok": True})
        print(f"STEP ok   {label}", flush=True)
        return value
    except Exception as exc:
        result["steps"].append({"step": label, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        print(f"STEP FAIL {label}: {type(exc).__name__}: {exc}", flush=True)
        traceback.print_exc()
        return None


def finish():
    Path(request["result"]).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print("CONVERSION WRITTEN", flush=True)


# -- load ------------------------------------------------------------------------

kind = source.suffix.lower()

if kind == ".blend":
    bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
elif kind == ".fbx":
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.import_scene.fbx(filepath=str(source))
elif kind in (".glb", ".gltf"):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
else:
    result["warnings"].append(f"Freya cannot convert {kind} files.")
    finish()
    raise SystemExit(0)

old = bpy.data.objects.get(request["rig"])

if old is None or old.type != "ARMATURE":
    result["warnings"].append("The skeleton named by the inspection was not found.")
    finish()
    raise SystemExit(0)

old.data.pose_position = "REST"
bpy.context.view_layer.update()
old_bones = old.data.bones
old_world = old.matrix_world.copy()

KEEP = [
    obj for obj in bpy.data.objects
    if obj.type == "MESH"
    and len(obj.data.polygons) > 0
    and any(m.type == "ARMATURE" and m.object == old for m in obj.modifiers)
]

if not KEEP:
    result["warnings"].append("Nothing in the file is attached to its skeleton.")
    finish()
    raise SystemExit(0)

top = max((obj.matrix_world @ v.co).z for obj in KEEP for v in obj.data.vertices)
bottom = min((obj.matrix_world @ v.co).z for obj in KEEP for v in obj.data.vertices)
height = top - bottom
# A person is between about one and two and a half metres tall. A model a
# hundred times that was made in centimetres; a thousand times, millimetres.
SCALE = 1.0

for unit in (1.0, 0.01, 0.001, 0.0254, 100.0):
    if 0.9 <= height * unit <= 2.6:
        SCALE = unit
        break
else:
    result["warnings"].append(
        f"The model is {height:.2f} units tall, which is not a plausible human "
        "size in any common unit. It was left at its own size."
    )

# -- which new bone each old bone's weights go to ---------------------------------

SIDES = {"l": "left", "r": "right"}
DIRECT = {
    "root.x": "hips", "spine_01.x": "spine", "spine_02.x": "chest",
    "spine_03.x": "upperChest", "spine_04.x": "upperChest", "spine_05.x": "upperChest",
    "neck.x": "neck", "subneck_twist_1.x": "neck", "head.x": "head",
    "DEF_eye.L": "leftEye", "DEF_eye.R": "rightEye",
}
PER_SIDE = [
    (r"^shoulder", "Shoulder"),
    (r"^(arm_stretch|arm_twist|c_arm_twist_offset)", "UpperArm"),
    (r"^forearm_(stretch|twist)", "LowerArm"),
    (r"^hand$", "Hand"),
    (r"^thigh_(stretch|twist)", "UpperLeg"),
    (r"^leg_(stretch|twist)", "LowerLeg"),
    (r"^foot$", "Foot"),
    (r"^toes_", "Toes"),
    (r"^thumb1$", "ThumbMetacarpal"), (r"^c_thumb2$", "ThumbProximal"), (r"^c_thumb3$", "ThumbDistal"),
]
for finger, name in (("index", "Index"), ("middle", "Middle"), ("ring", "Ring"), ("pinky", "Little")):
    PER_SIDE += [
        (rf"^(c_{finger}1_base|{finger}1)$", f"{name}Proximal"),
        (rf"^c_{finger}2$", f"{name}Intermediate"),
        (rf"^c_{finger}3$", f"{name}Distal"),
    ]
CONTROLLERS = {
    r"^c_head": "head", r"^c_neck": "neck", r"^c_root": "hips", r"^c_spine_01": "spine",
    r"^c_spine_02": "chest", r"^c_spine_0[345]": "upperChest", r"^c_traj|^c_pos": "hips",
}

PARENTS = {
    "hips": None, "spine": "hips", "chest": "spine", "upperChest": "chest",
    "neck": "upperChest", "head": "neck", "leftEye": "head", "rightEye": "head",
}
for side in ("left", "right"):
    PARENTS.update({
        f"{side}Shoulder": "upperChest", f"{side}UpperArm": f"{side}Shoulder",
        f"{side}LowerArm": f"{side}UpperArm", f"{side}Hand": f"{side}LowerArm",
        f"{side}UpperLeg": "hips", f"{side}LowerLeg": f"{side}UpperLeg",
        f"{side}Foot": f"{side}LowerLeg", f"{side}Toes": f"{side}Foot",
        f"{side}ThumbMetacarpal": f"{side}Hand", f"{side}ThumbProximal": f"{side}ThumbMetacarpal",
        f"{side}ThumbDistal": f"{side}ThumbProximal",
    })
    for finger in ("Index", "Middle", "Ring", "Little"):
        PARENTS.update({
            f"{side}{finger}Proximal": f"{side}Hand",
            f"{side}{finger}Intermediate": f"{side}{finger}Proximal",
            f"{side}{finger}Distal": f"{side}{finger}Intermediate",
        })

REQUIRED = [
    "hips", "spine", "head",
    "leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg", "rightLowerLeg", "rightFoot",
]


def target_for(name):
    if name in DIRECT:
        return DIRECT[name]
    found = re.match(r"^(.*)\.(l|r)$", name)
    if found:
        stem, side = found.groups()
        for pattern, part in PER_SIDE:
            if re.match(pattern, stem):
                return SIDES[side] + part
    if name.startswith(("DEF-", "DEF_", "lid.")):
        return "head"
    return None


def resolve(name):
    """The new bone for any old bone: its own, or that of the nearest ancestor."""
    bone = old_bones.get(name)
    for _ in range(80):
        if bone is None:
            return None
        target = target_for(bone.name)
        if target:
            return target
        for pattern, controller in CONTROLLERS.items():
            if re.match(pattern, bone.name):
                return controller
        bone = bone.parent
    return None


def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


# -- the skeleton ------------------------------------------------------------------


def rebuild_skeleton():
    """Replace an Auto-Rig Pro rig with a plain humanoid skeleton."""
    preferred = ("root.x", "spine_01.x", "spine_02.x", "spine_03.x", "neck.x", "head.x", "arm_stretch",
                 "forearm_stretch", "thigh_twist", "leg_stretch", "index1", "middle1", "ring1", "pinky1")
    places = {}

    for bone in old_bones:
        target = target_for(bone.name)
        if target is None:
            continue
        rank = 0 if bone.name.startswith(preferred) else 1
        if target not in places or rank < places[target][0]:
            places[target] = (rank, old_world @ bone.head_local, old_world @ bone.tail_local)

    absent = [name for name in REQUIRED if name not in places]
    if absent:
        raise ValueError("the skeleton has no bone for: " + ", ".join(absent))

    data = bpy.data.armatures.new("Avatar")
    rig = bpy.data.objects.new("Avatar", data)
    bpy.context.scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    made = {}

    for name in PARENTS:
        if name not in places:
            continue
        _, head, tail = places[name]
        bone = data.edit_bones.new(name)
        bone.head = head * SCALE
        bone.tail = tail * SCALE
        if (bone.tail - bone.head).length < 0.01:
            bone.tail = bone.head + Vector((0, 0, 0.03))
        made[name] = bone

    for name, bone in made.items():
        parent = PARENTS[name]
        while parent is not None and parent not in made:
            parent = PARENTS[parent]
        if parent is not None:
            bone.parent = made[parent]

    bpy.ops.object.mode_set(mode="OBJECT")

    return rig


def reweight(obj, rig):
    mesh = obj.data
    mesh.transform(Matrix.Scale(SCALE, 4) @ obj.matrix_world, shape_keys=True)
    obj.parent = None
    obj.matrix_world = Matrix.Identity(4)

    names = {group.index: group.name for group in obj.vertex_groups}
    targets = {index: resolve(name) for index, name in names.items()}
    weights = []

    for vertex in mesh.vertices:
        totals = defaultdict(float)
        for group in vertex.groups:
            target = targets.get(group.group)
            if target is not None:
                totals[target] += group.weight
        if not totals:
            # A point attached to nothing follows whatever its neighbours
            # mostly follow; failing that, the head or hips by height.
            totals["head" if (mesh.vertices[vertex.index].co.z > (top - height * 0.2) * SCALE) else "hips"] = 1.0
        scale = sum(totals.values())
        weights.append({name: weight / scale for name, weight in totals.items()})

    for group in list(obj.vertex_groups):
        obj.vertex_groups.remove(group)

    groups = {}
    for index, totals in enumerate(weights):
        for name, weight in totals.items():
            if name not in groups:
                groups[name] = obj.vertex_groups.new(name=name)
            groups[name].add([index], weight, "REPLACE")

    for modifier in list(obj.modifiers):
        obj.modifiers.remove(modifier)

    obj.modifiers.new("Armature", "ARMATURE").object = rig
    obj.parent = rig


def keep_skeleton():
    """Keep a simple skeleton as it is, resized, and let the VRM add-on work
    out which bone is which."""
    for obj in KEEP:
        for modifier in list(obj.modifiers):
            if modifier.type != "ARMATURE":
                obj.modifiers.remove(modifier)

    if SCALE != 1.0:
        old.scale = old.scale * SCALE
        old.location = old.location * SCALE
        bpy.ops.object.select_all(action="DESELECT")
        old.select_set(True)
        for obj in KEEP:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = old
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    return old


if request["rig_kind"] == "auto-rig-pro":
    rig = step("rebuild the skeleton as a plain humanoid one", rebuild_skeleton)
    if rig is not None:
        for obj in KEEP:
            step(f"re-attach {obj.name.strip()}", lambda: reweight(obj, rig))
else:
    rig = step("resize the skeleton", keep_skeleton)

if rig is None:
    result["warnings"].append("The skeleton could not be made into a humanoid one.")
    finish()
    raise SystemExit(0)

for obj in KEEP:
    keys = obj.data.shape_keys
    if keys is not None:
        keys.animation_data_clear()
        for block in keys.key_blocks:
            block.value = 0.0
            block.mute = False

# -- tidy the scene ------------------------------------------------------------------


def join(pattern, name):
    pieces = [o for o in KEEP if re.match(pattern, o.name, re.I) and o.data.shape_keys is None]
    if len(pieces) < 2:
        return
    bpy.ops.object.select_all(action="DESELECT")
    for piece in pieces:
        piece.select_set(True)
    bpy.context.view_layer.objects.active = pieces[0]
    bpy.ops.object.join()
    pieces[0].name = name
    for piece in pieces[1:]:
        KEEP.remove(piece)


# Hair is often dozens of small pieces sharing one material.
step("join hair pieces", lambda: join(r"^hair", "Hair"))
step("join accessories", lambda: join(r"^accessor", "Accessories"))

for obj in list(bpy.data.objects):
    if obj not in KEEP and obj is not rig:
        bpy.data.objects.remove(obj, do_unlink=True)

# -- materials -------------------------------------------------------------------------

MAX_TEXTURE = request.get("max_texture", 2048)


def image_into(material, socket_name):
    shader = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if shader is None or socket_name not in shader.inputs:
        return None
    todo = [link.from_node for link in shader.inputs[socket_name].links]
    seen = set()
    while todo:
        node = todo.pop()
        if node in seen:
            continue
        seen.add(node)
        if node.type == "TEX_IMAGE" and node.image:
            return node.image
        for socket in node.inputs:
            todo.extend(link.from_node for link in socket.links)
    return None


def remove_clear_layers():
    """An eye is often two surfaces: the coloured part, and a clear coating
    over it with no picture of its own. Exported, the coating turns solid and
    hides the eye, so it is removed."""
    for obj in KEEP:
        if not re.search(r"eye(?!brow|lash)", obj.name, re.I) or len(obj.material_slots) < 2:
            continue
        pictured = [bool(s.material and s.material.use_nodes and image_into(s.material, "Base Color"))
                    for s in obj.material_slots]
        if not any(pictured) or all(pictured):
            continue
        doomed = {index for index, has in enumerate(pictured) if not has}
        mesh = bmesh.new()
        mesh.from_mesh(obj.data)
        faces = [face for face in mesh.faces if face.material_index in doomed]
        bmesh.ops.delete(mesh, geom=faces, context="FACES")
        mesh.to_mesh(obj.data)
        mesh.free()


def simplify(material):
    if not material.use_nodes:
        return
    base = image_into(material, "Base Color")
    normal = image_into(material, "Normal")
    old_shader = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    colour = tuple(old_shader.inputs["Base Color"].default_value) if old_shader else (0.8, 0.8, 0.8, 1)
    roughness = old_shader.inputs["Roughness"].default_value if old_shader else 0.6
    # Hair, lashes and brows drawn on flat cards need their edges cut out.
    cutout = bool(
        base is not None
        and base.channels == 4
        and re.search(r"hair|lash|brow|fur", material.name, re.I)
    )

    tree = material.node_tree
    tree.nodes.clear()
    output_node = tree.nodes.new("ShaderNodeOutputMaterial")
    shader = tree.nodes.new("ShaderNodeBsdfPrincipled")
    tree.links.new(shader.outputs[0], output_node.inputs[0])
    shader.inputs["Base Color"].default_value = colour
    shader.inputs["Roughness"].default_value = max(roughness, 0.35)

    for image in (base, normal):
        if image is not None and max(image.size) > MAX_TEXTURE:
            factor = MAX_TEXTURE / max(image.size)
            image.scale(max(int(image.size[0] * factor), 1), max(int(image.size[1] * factor), 1))
            image.pack()

    if base is not None:
        picture = tree.nodes.new("ShaderNodeTexImage")
        picture.image = base
        tree.links.new(picture.outputs["Color"], shader.inputs["Base Color"])
        if cutout:
            rounder = tree.nodes.new("ShaderNodeMath")
            rounder.operation = "ROUND"
            tree.links.new(picture.outputs["Alpha"], rounder.inputs[0])
            tree.links.new(rounder.outputs[0], shader.inputs["Alpha"])

    if normal is not None:
        picture = tree.nodes.new("ShaderNodeTexImage")
        picture.image = normal
        picture.image.colorspace_settings.name = "Non-Color"
        bump = tree.nodes.new("ShaderNodeNormalMap")
        tree.links.new(picture.outputs["Color"], bump.inputs["Color"])
        tree.links.new(bump.outputs["Normal"], shader.inputs["Normal"])


step("remove clear eye coatings", remove_clear_layers)


def materials():
    for material in {s.material for o in KEEP for s in o.material_slots if s.material}:
        simplify(material)


step("simplify materials", materials)

# -- VRM ---------------------------------------------------------------------------------

extension = rig.data.vrm_addon_extension
extension.spec_version = "1.0"
meta = extension.vrm1.meta
meta.vrm_name = request["name"]
meta.version = "1"
meta.authors.add().value = request.get("author") or "Unknown"
meta.copyright_information = request.get("copyright", "")
# Freya did not make this model and does not know its terms, so the file says
# the most cautious thing: only someone its author has licensed may use it.
meta.avatar_permission = "onlySeparatelyLicensedPerson"
meta.commercial_usage = "personalNonProfit"
meta.credit_notation = "required"
meta.allow_redistribution = False
meta.modification = "prohibited"


def humanoid():
    human = extension.vrm1.humanoid.human_bones

    if request["rig_kind"] == "auto-rig-pro":
        for name in rig.data.bones.keys():
            slot = getattr(human, snake(name), None)
            if slot is not None:
                slot.node.bone_name = name
    else:
        bpy.ops.object.select_all(action="DESELECT")
        rig.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.vrm.assign_vrm1_humanoid_human_bones_automatically(armature_object_name=rig.name)

    absent = [name for name in REQUIRED if not getattr(human, snake(name)).node.bone_name]
    result["bones_missing"] = absent

    if absent:
        raise ValueError("no bone could be found for: " + ", ".join(absent))


step("say which bone is which", humanoid)
bones_ok = result["steps"][-1]["ok"]

RECIPES = {
    "aa": {"jawOpen": 0.65},
    "ih": {"jawOpen": 0.2, "mouthStretchLeft": 0.5, "mouthStretchRight": 0.5},
    "ou": {"jawOpen": 0.15, "mouthPucker": 0.85},
    "ee": {"jawOpen": 0.15, "mouthSmileLeft": 0.35, "mouthSmileRight": 0.35,
           "mouthStretchLeft": 0.3, "mouthStretchRight": 0.3},
    "oh": {"jawOpen": 0.4, "mouthFunnel": 0.75},
    "blink": {"eyeBlinkLeft": 1.0, "eyeBlinkRight": 1.0},
    "blink_left": {"eyeBlinkLeft": 1.0},
    "blink_right": {"eyeBlinkRight": 1.0},
    "happy": {"mouthSmileLeft": 0.8, "mouthSmileRight": 0.8, "cheekSquintLeft": 0.4, "cheekSquintRight": 0.4},
    "sad": {"mouthFrownLeft": 0.7, "mouthFrownRight": 0.7, "browInnerUp": 0.7},
    "angry": {"browDownLeft": 0.9, "browDownRight": 0.9, "noseSneerLeft": 0.4, "noseSneerRight": 0.4,
              "mouthPressLeft": 0.4, "mouthPressRight": 0.4},
    "surprised": {"eyeWideLeft": 0.9, "eyeWideRight": 0.9, "browInnerUp": 0.8,
                  "browOuterUpLeft": 0.6, "browOuterUpRight": 0.6, "jawOpen": 0.3},
    "relaxed": {"mouthSmileLeft": 0.3, "mouthSmileRight": 0.3, "eyeSquintLeft": 0.2, "eyeSquintRight": 0.2},
    "look_up": {"eyeLookUpLeft": 1.0, "eyeLookUpRight": 1.0},
    "look_down": {"eyeLookDownLeft": 1.0, "eyeLookDownRight": 1.0},
    "look_left": {"eyeLookOutLeft": 1.0, "eyeLookInRight": 1.0},
    "look_right": {"eyeLookInLeft": 1.0, "eyeLookOutRight": 1.0},
}
FACE_UNITS = sorted({unit for recipe in RECIPES.values() for unit in recipe} | set(request.get("face_units", [])))


def bind(target, unit, weight):
    """Attach one face shape to an expression on every part that has it:
    the face, and the lashes, teeth and tongue that move with it."""
    found = False
    for obj in KEEP:
        keys = obj.data.shape_keys
        if keys is not None and unit in keys.key_blocks:
            entry = target.morph_target_binds.add()
            entry.node.mesh_object_name = obj.name
            entry.index = unit
            entry.weight = weight
            found = True
    return found


def expressions():
    preset = extension.vrm1.expressions.preset
    made = 0

    for expression, recipe in RECIPES.items():
        target = getattr(preset, expression)
        target.morph_target_binds.clear()
        if any([bind(target, unit, weight) for unit, weight in recipe.items()]):
            made += 1

    # Every individual face shape as well, under its own name, for finer
    # animation later. They add nothing to the size of the file: the shapes
    # are already in it, and this only names them.
    custom = 0
    for unit in FACE_UNITS:
        if not any(o.data.shape_keys is not None and unit in o.data.shape_keys.key_blocks for o in KEEP):
            continue
        bpy.ops.vrm.add_vrm1_expressions_custom_expression(
            armature_object_name=rig.name, custom_expression_name=unit)
        bind(extension.vrm1.expressions.custom[-1], unit, 1.0)
        custom += 1

    result["expressions"] = made
    result["face_shapes"] = custom

    if made == 0:
        result["warnings"].append("The model has no standard face shapes, so it has no expressions.")


step("set up expressions", expressions)


def export():
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.export_scene.vrm(filepath=str(output), armature_object_name=rig.name, ignore_warning=True)

    if not output.is_file() or output.stat().st_size < 1024:
        raise ValueError("Blender wrote no avatar file")


if bones_ok:
    step("write the avatar file", export)

if bones_ok and result["steps"][-1]["ok"] and output.is_file():
    result["ok"] = True
    result["scale"] = SCALE
    result["size"] = output.stat().st_size

finish()
