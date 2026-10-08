from dataclasses import dataclass


@dataclass(frozen=True)
class Appearance:
    """
    One way of drawing the avatar.

    Every appearance is the same character: the same proportions,
    skeleton, expressions, and animation state. An appearance only
    changes materials and effects, which is what lets a renderer switch
    between them while she is on screen.

    The fields are hints a renderer may use as far as it is able. The
    placeholder renderer uses the colours, opacity, and the two effect
    switches; a full 3D renderer would map them to materials.
    """

    id: str
    name: str
    summary: str
    # How demanding it is to draw, lowest first: 0, 1, 2.
    cost: int
    skin: str
    hair: str
    clothing: str
    outline: str
    accent: str
    opacity: float = 1.0
    scanlines: bool = False
    glow: bool = False


APPEARANCES = {
    appearance.id: appearance
    for appearance in (
        Appearance(
            id="lightweight",
            name="Lightweight",
            summary="A simple flat figure for everyday use and modest hardware.",
            cost=0,
            skin="#8fa8ff",
            hair="#8fa8ff",
            clothing="#7c9cff",
            outline="#2b3566",
            accent="#ffffff",
        ),
        Appearance(
            id="realistic",
            name="Realistic",
            summary=(
                "Natural colours for skin, hair, and clothing. A placeholder "
                "until a photorealistic character is added."
            ),
            cost=2,
            skin="#e8b796",
            hair="#5a3a22",
            clothing="#3f6f8f",
            outline="#3a2a20",
            accent="#ffffff",
        ),
        Appearance(
            id="holographic",
            name="Holographic",
            summary="A translucent, glowing figure with scanlines.",
            cost=1,
            skin="#7ef0ff",
            hair="#4fd8ff",
            clothing="#39b9e6",
            outline="#b8fbff",
            accent="#e9feff",
            opacity=0.72,
            scanlines=True,
            glow=True,
        ),
    )
}

DEFAULT_APPEARANCE = "lightweight"

EXPRESSIONS = ("neutral", "happy", "thinking", "surprised", "concerned")

DEFAULT_EXPRESSION = "neutral"


def cheapest_appearance() -> str:
    """
    The appearance to fall back to when resources are short.
    """
    return min(APPEARANCES.values(), key=lambda appearance: appearance.cost).id
