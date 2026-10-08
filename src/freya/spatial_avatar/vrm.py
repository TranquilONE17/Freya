"""
Reading VRM avatar files.

A VRM file is a glTF binary (GLB) file with extra data describing a
humanoid avatar: who made it, the terms it may be used under, its
skeleton, and its facial expressions. This module reads that
description. It does not load the 3D model itself.

Every VRM file is treated as untrusted input, because they are
downloaded from other people. The file is never executed (the format
has no code in it); sizes and offsets are checked before anything is
read; text taken from it is cut to a sensible length and stripped of
control characters; and nothing in it is ever treated as an
instruction.
"""
import hashlib
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple


GLB_MAGIC = 0x46546C67      # "glTF"
CHUNK_JSON = 0x4E4F534A     # "JSON"
CHUNK_BIN = 0x004E4942      # "BIN"

MAX_FILE_BYTES = 300 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 8 * 1024 * 1024
MAX_TEXT = 200

# Who may use the avatar.
EVERYONE = "everyone"
LICENSED = "licensed"          # only people the author has licensed
AUTHOR_ONLY = "author-only"
UNKNOWN = "unknown"

# The bones a VRM humanoid must have.
REQUIRED_BONES = (
    "hips", "spine", "head",
    "leftUpperArm", "leftLowerArm", "leftHand",
    "rightUpperArm", "rightLowerArm", "rightHand",
    "leftUpperLeg", "leftLowerLeg", "leftFoot",
    "rightUpperLeg", "rightLowerLeg", "rightFoot",
)

# Mouth shapes used for speech, by their VRM 1.0 names, and the names
# VRM 0.x used for the same shapes.
VISEMES = ("aa", "ih", "ou", "ee", "oh")
VRM0_NAMES = {
    "a": "aa", "i": "ih", "u": "ou", "e": "ee", "o": "oh",
    "joy": "happy", "sorrow": "sad", "fun": "relaxed",
    "blink_l": "blinkLeft", "blink_r": "blinkRight",
    "lookup": "lookUp", "lookdown": "lookDown",
    "lookleft": "lookLeft", "lookright": "lookRight",
}


class VrmError(Exception):
    """
    The file is not a usable VRM file. The message is safe to show.
    """


def _text(value, limit=MAX_TEXT) -> str:
    """
    A string from the file made safe to store and show.
    """
    if not isinstance(value, str):
        return ""

    cleaned = "".join(
        character if character.isprintable() else " " for character in value
    )

    return " ".join(cleaned.split())[:limit]


def _texts(value, limit=8) -> List[str]:
    if isinstance(value, str):
        value = [value]

    if not isinstance(value, list):
        return []

    return [text for text in (_text(item) for item in value[:limit]) if text]


@dataclass
class VrmLicence:
    """
    The terms a VRM file states for itself, in one form whichever
    version of the format wrote them. Empty or "unknown" means the file
    did not say.
    """

    who_may_use: str = UNKNOWN
    commercial_use: str = ""
    violent_use: str = ""
    sexual_use: str = ""
    political_or_religious_use: str = ""
    antisocial_or_hate_use: str = ""
    credit: str = ""
    redistribution: str = ""
    modification: str = ""
    licence_name: str = ""
    licence_url: str = ""
    other_terms_url: str = ""

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    def summary(self) -> List[str]:
        """
        The terms as plain sentences, most important first.
        """
        who = {
            EVERYONE: "Anyone may use this avatar.",
            LICENSED: "Only people the author has licensed may use this avatar.",
            AUTHOR_ONLY: "Only its author may use this avatar.",
            UNKNOWN: "The file does not say who may use this avatar.",
        }[self.who_may_use]
        lines = [who]

        for label, value in (
            ("Commercial use", self.commercial_use),
            ("Redistribution", self.redistribution),
            ("Modification", self.modification),
            ("Credit", self.credit),
            ("Violent content", self.violent_use),
            ("Sexual content", self.sexual_use),
            ("Political or religious use", self.political_or_religious_use),
            ("Antisocial or hateful use", self.antisocial_or_hate_use),
            ("Licence", self.licence_name),
        ):
            if value:
                lines.append(f"{label}: {value}.")

        return lines


@dataclass
class VrmInfo:
    """
    What a VRM file says about itself.
    """

    sha256: str
    file_name: str
    size: int
    spec: str                     # "0.x" or "1.0"
    spec_version: str
    name: str
    authors: List[str]
    version: str
    contact: str
    licence: VrmLicence
    expressions: List[str]
    visemes: List[str]
    bones: List[str]
    missing_bones: List[str]
    stats: dict
    generator: str
    # Where the thumbnail image is inside the file, if there is one:
    # (media type, offset, length).
    thumbnail: Optional[Tuple[str, int, int]] = None
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "sha256": self.sha256,
            "file_name": self.file_name,
            "size": self.size,
            "spec": self.spec,
            "spec_version": self.spec_version,
            "name": self.name,
            "authors": self.authors,
            "version": self.version,
            "contact": self.contact,
            "licence": self.licence.as_dict(),
            "licence_summary": self.licence.summary(),
            "expressions": self.expressions,
            "visemes": self.visemes,
            "bones": len(self.bones),
            "missing_bones": self.missing_bones,
            "stats": self.stats,
            "generator": self.generator,
            "has_thumbnail": self.thumbnail is not None,
            "thumbnail": list(self.thumbnail) if self.thumbnail else None,
            "warnings": self.warnings,
        }


# -- the container ------------------------------------------------------------


def _read_chunks(handle, size: int):
    """
    Returns (json bytes, offset of binary data, length of binary data).
    """
    header = handle.read(12)

    if len(header) != 12:
        raise VrmError("The file is too short to be a VRM file.")

    magic, version, length = struct.unpack("<III", header)

    if magic != GLB_MAGIC:
        raise VrmError("This is not a VRM file (it is not a glTF binary file).")

    if version != 2:
        raise VrmError("This glTF version is not supported.")

    if length > size:
        raise VrmError("The file is cut short or damaged.")

    chunk = handle.read(8)

    if len(chunk) != 8:
        raise VrmError("The file is cut short or damaged.")

    json_length, json_type = struct.unpack("<II", chunk)

    if json_type != CHUNK_JSON:
        raise VrmError("The file's description is missing.")

    if json_length > MAX_JSON_BYTES or 20 + json_length > size:
        raise VrmError("The file's description is too large or damaged.")

    json_bytes = handle.read(json_length)

    if len(json_bytes) != json_length:
        raise VrmError("The file is cut short or damaged.")

    binary_offset = binary_length = 0
    chunk = handle.read(8)

    if len(chunk) == 8:
        length, kind = struct.unpack("<II", chunk)
        start = 20 + json_length + 8

        if kind == CHUNK_BIN and start + length <= size:
            binary_offset, binary_length = start, length

    return json_bytes, binary_offset, binary_length


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


# -- what the description says -------------------------------------------------


def _allow(value) -> str:
    """
    A yes/no term in either version's spelling, as a word.
    """
    if value is True:
        return "allowed"

    if value is False:
        return "not allowed"

    text = _text(value).lower()

    if text in ("allow", "allowed"):
        return "allowed"

    if text in ("disallow", "disallowed"):
        return "not allowed"

    return ""


def _licence_v0(meta: dict) -> VrmLicence:
    who = {
        "everyone": EVERYONE,
        "explicitlylicensedperson": LICENSED,
        "onlyauthor": AUTHOR_ONLY,
    }.get(_text(meta.get("allowedUserName")).lower(), UNKNOWN)
    name = _text(meta.get("licenseName"))
    redistribution = ""

    if name.lower() == "redistribution_prohibited":
        redistribution = "not allowed"
    elif name.lower().startswith("cc"):
        redistribution = "allowed under " + name.replace("_", " ")

    return VrmLicence(
        who_may_use=who,
        # (sic) the format's own field names are misspelled.
        commercial_use=_allow(meta.get("commercialUssageName")),
        violent_use=_allow(meta.get("violentUssageName")),
        sexual_use=_allow(meta.get("sexualUssageName")),
        redistribution=redistribution,
        licence_name=name.replace("_", " "),
        licence_url=_text(meta.get("otherLicenseUrl"), 500),
        other_terms_url=_text(meta.get("otherPermissionUrl"), 500),
    )


def _licence_v1(meta: dict) -> VrmLicence:
    who = {
        "everyone": EVERYONE,
        "onlyseparatelylicensedperson": LICENSED,
        "onlyauthor": AUTHOR_ONLY,
    }.get(_text(meta.get("avatarPermission")).lower(), UNKNOWN)
    commercial = {
        "personalnonprofit": "not allowed (personal, non-profit use only)",
        "personalprofit": "allowed for individuals",
        "corporation": "allowed, including by companies",
    }.get(_text(meta.get("commercialUsage")).lower(), "")
    modification = {
        "prohibited": "not allowed",
        "allowmodification": "allowed, but the result may not be redistributed",
        "allowmodificationredistribution": "allowed, and the result may be redistributed",
    }.get(_text(meta.get("modification")).lower(), "")
    credit = {
        "required": "required",
        "unnecessary": "not required",
    }.get(_text(meta.get("creditNotation")).lower(), "")

    return VrmLicence(
        who_may_use=who,
        commercial_use=commercial,
        violent_use=_allow(meta.get("allowExcessivelyViolentUsage")),
        sexual_use=_allow(meta.get("allowExcessivelySexualUsage")),
        political_or_religious_use=_allow(meta.get("allowPoliticalOrReligiousUsage")),
        antisocial_or_hate_use=_allow(meta.get("allowAntisocialOrHateUsage")),
        credit=credit,
        redistribution=_allow(meta.get("allowRedistribution")),
        modification=modification,
        licence_url=_text(meta.get("licenseUrl"), 500),
        other_terms_url=_text(meta.get("otherLicenseUrl"), 500),
    )


def _expressions_v0(extension: dict) -> List[str]:
    groups = (extension.get("blendShapeMaster") or {}).get("blendShapeGroups")
    names = []

    if isinstance(groups, list):
        for group in groups[:256]:
            if not isinstance(group, dict):
                continue

            preset = _text(group.get("presetName")).lower()
            name = preset if preset and preset != "unknown" else _text(group.get("name"))

            if name:
                names.append(VRM0_NAMES.get(name.lower(), name))

    return names


def _expressions_v1(extension: dict) -> List[str]:
    expressions = extension.get("expressions") or {}
    names = []

    for kind in ("preset", "custom"):
        group = expressions.get(kind)

        if isinstance(group, dict):
            names.extend(_text(name) for name in list(group)[:256])

    return [name for name in names if name]


def _bones_v0(extension: dict) -> List[str]:
    bones = (extension.get("humanoid") or {}).get("humanBones")

    if not isinstance(bones, list):
        return []

    return [
        _text(bone.get("bone"))
        for bone in bones[:128]
        if isinstance(bone, dict) and _text(bone.get("bone"))
    ]


def _bones_v1(extension: dict) -> List[str]:
    bones = (extension.get("humanoid") or {}).get("humanBones")

    return [_text(name) for name in list(bones)[:128]] if isinstance(bones, dict) else []


def _stats(document: dict) -> dict:
    def count(key):
        value = document.get(key)

        return len(value) if isinstance(value, list) else 0

    accessors = document.get("accessors")
    accessors = accessors if isinstance(accessors, list) else []
    triangles = vertices = primitives = 0

    for mesh in (document.get("meshes") or [])[:4096]:
        if not isinstance(mesh, dict):
            continue

        for primitive in (mesh.get("primitives") or [])[:4096]:
            if not isinstance(primitive, dict):
                continue

            primitives += 1

            def accessor_count(index):
                if isinstance(index, int) and 0 <= index < len(accessors):
                    value = accessors[index].get("count") if isinstance(accessors[index], dict) else 0

                    return value if isinstance(value, int) and value > 0 else 0

                return 0

            triangles += accessor_count(primitive.get("indices")) // 3
            attributes = primitive.get("attributes")

            if isinstance(attributes, dict):
                vertices += accessor_count(attributes.get("POSITION"))

    return {
        "meshes": count("meshes"),
        "primitives": primitives,
        "triangles": triangles,
        "vertices": vertices,
        "materials": count("materials"),
        "textures": count("textures"),
        "nodes": count("nodes"),
    }


def _thumbnail(document, image_index, binary_offset, binary_length):
    """
    Where an image stored inside the file is: (media type, offset,
    length), or None when it is missing, external, or implausible.
    """
    images = document.get("images")
    views = document.get("bufferViews")

    if (
        not isinstance(image_index, int)
        or isinstance(image_index, bool)
        or not isinstance(images, list)
        or not isinstance(views, list)
        or not 0 <= image_index < len(images)
        or not isinstance(images[image_index], dict)
    ):
        return None

    image = images[image_index]
    view_index = image.get("bufferView")

    if (
        not isinstance(view_index, int)
        or not 0 <= view_index < len(views)
        or not isinstance(views[view_index], dict)
    ):
        return None

    view = views[view_index]
    offset = view.get("byteOffset", 0)
    length = view.get("byteLength")

    if (
        view.get("buffer", 0) != 0
        or not isinstance(offset, int)
        or not isinstance(length, int)
        or offset < 0
        or not 0 < length <= MAX_THUMBNAIL_BYTES
        or offset + length > binary_length
    ):
        return None

    media = _text(image.get("mimeType")).lower()

    if media not in ("image/png", "image/jpeg"):
        return None

    return (media, binary_offset + offset, length)


def read_vrm(path) -> VrmInfo:
    """
    Read what a VRM file says about itself. Raises VrmError when the
    file is not a readable VRM file.
    """
    path = Path(path)

    try:
        size = path.stat().st_size
    except OSError:
        raise VrmError("The file could not be read.")

    if size > MAX_FILE_BYTES:
        raise VrmError(
            f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB."
        )

    try:
        with open(path, "rb") as handle:
            json_bytes, binary_offset, binary_length = _read_chunks(handle, size)
    except OSError:
        raise VrmError("The file could not be read.")

    try:
        document = json.loads(json_bytes.decode("utf-8"))
    except (ValueError, RecursionError):
        raise VrmError("The file's description could not be read.")

    if not isinstance(document, dict):
        raise VrmError("The file's description could not be read.")

    extensions = document.get("extensions")
    extensions = extensions if isinstance(extensions, dict) else {}
    warnings: List[str] = []

    if isinstance(extensions.get("VRMC_vrm"), dict):
        extension = extensions["VRMC_vrm"]
        meta = extension.get("meta") if isinstance(extension.get("meta"), dict) else {}
        spec = "1.0"
        spec_version = _text(extension.get("specVersion"), 20)
        name = _text(meta.get("name"))
        authors = _texts(meta.get("authors"))
        contact = _text(meta.get("contactInformation"))
        licence = _licence_v1(meta)
        expressions = _expressions_v1(extension)
        bones = _bones_v1(extension)
        thumbnail_index = meta.get("thumbnailImage")
    elif isinstance(extensions.get("VRM"), dict):
        extension = extensions["VRM"]
        meta = extension.get("meta") if isinstance(extension.get("meta"), dict) else {}
        spec = "0.x"
        spec_version = _text(extension.get("specVersion"), 20) or "0.0"
        name = _text(meta.get("title"))
        authors = _texts(meta.get("author"))
        contact = _text(meta.get("contactInformation"))
        licence = _licence_v0(meta)
        expressions = _expressions_v0(extension)
        bones = _bones_v0(extension)
        # In VRM 0.x the thumbnail is a texture, which names an image.
        thumbnail_index = None
        textures = document.get("textures")
        texture = meta.get("texture")

        if (
            isinstance(texture, int)
            and isinstance(textures, list)
            and 0 <= texture < len(textures)
            and isinstance(textures[texture], dict)
        ):
            thumbnail_index = textures[texture].get("source")
    else:
        raise VrmError(
            "This is a 3D model, but not a VRM avatar: it has no avatar "
            "description."
        )

    missing = [bone for bone in REQUIRED_BONES if bone not in bones]

    if missing:
        warnings.append(
            "It is missing parts of the skeleton an avatar needs: "
            + ", ".join(missing[:6])
            + ("…" if len(missing) > 6 else "")
            + "."
        )

    visemes = [name for name in VISEMES if name in expressions]

    if len(visemes) < len(VISEMES):
        warnings.append("It lacks some mouth shapes, so lip movement will be limited.")

    if licence.who_may_use == UNKNOWN:
        warnings.append("It does not state who may use it.")

    stats = _stats(document)

    if stats["triangles"] > 200_000:
        warnings.append("It is a very detailed model and may be slow to draw.")

    asset = document.get("asset") if isinstance(document.get("asset"), dict) else {}

    return VrmInfo(
        sha256=_sha256(path),
        file_name=path.name,
        size=size,
        spec=spec,
        spec_version=spec_version,
        name=name or path.stem[:MAX_TEXT],
        authors=authors,
        version=_text(meta.get("version"), 40),
        contact=contact,
        licence=licence,
        expressions=sorted(set(expressions)),
        visemes=visemes,
        bones=bones,
        missing_bones=missing,
        stats=stats,
        generator=_text(asset.get("generator"), 80),
        thumbnail=_thumbnail(document, thumbnail_index, binary_offset, binary_length),
        warnings=warnings,
    )


def read_thumbnail(path, location) -> Optional[Tuple[str, bytes]]:
    """
    The thumbnail image a VRM file carries, as (media type, bytes), or
    None. The bytes are returned only if they really begin as the kind
    of image the file claims.
    """
    try:
        media, offset, length = location
        offset, length = int(offset), int(length)
    except (TypeError, ValueError):
        return None

    if media not in ("image/png", "image/jpeg") or not 0 < length <= MAX_THUMBNAIL_BYTES:
        return None

    try:
        with open(path, "rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
    except OSError:
        return None

    signature = b"\x89PNG\r\n\x1a\n" if media == "image/png" else b"\xff\xd8\xff"

    if len(data) != length or not data.startswith(signature):
        return None

    return (media, data)
