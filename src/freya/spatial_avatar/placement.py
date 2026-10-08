import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from freya.spatial_avatar.geometry import Rect


# The gap left between the avatar and what she points at, as a share
# of her own height.
GAP = 0.25
# How far from a target, in her own heights, still counts as beside it.
NEAR = 0.6


@dataclass(frozen=True)
class Placement:
    """
    Where the avatar should stand to point at something.

    covers_target is True only when there was nowhere inside her
    boundaries that left the target visible.
    """

    rect: Rect
    covers_target: bool


def keep_inside(rect: Rect, bounds: Rect, restricted: List[Rect]) -> Rect:
    """
    A rectangle moved as little as possible so that it is inside the
    boundary and, where that can be done, out of every restricted
    region. The boundary always wins: she is never moved outside it to
    get clear of a restricted region.
    """
    rect = rect.clamped_into(bounds)

    for region in restricted:
        if rect.overlap_area(region) <= 0:
            continue

        # Try stepping clear of the region in each direction and keep
        # the shortest step that stays inside the boundary.
        candidates = [
            rect.moved_to(region.left - rect.width, rect.top),
            rect.moved_to(region.right, rect.top),
            rect.moved_to(rect.left, region.top - rect.height),
            rect.moved_to(rect.left, region.bottom),
        ]
        clear = [
            candidate
            for candidate in candidates
            if bounds.contains(candidate)
            and all(candidate.overlap_area(other) <= 0 for other in restricted)
        ]

        if clear:
            rect = min(
                clear,
                key=lambda c: (c.left - rect.left) ** 2 + (c.top - rect.top) ** 2,
            )

    return rect


def place_beside(
    target: Rect,
    size: Tuple[float, float],
    bounds: Rect,
    restricted: Optional[List[Rect]] = None,
    current: Optional[Rect] = None,
) -> Placement:
    """
    Choose where to stand so as to point at a target without covering
    it.

    Candidates are tried beside, above, and below the target. One is
    acceptable when it is inside the boundary, clear of the target, and
    clear of every restricted region. The acceptable one nearest to
    where she already is wins, so she moves no further than needed.

    If nothing is acceptable (the target fills her boundary, say) she
    takes the position inside the boundary that hides the least of the
    target, and the result says that it is covered.
    """
    restricted = restricted or []
    width, height = size
    gap = height * GAP
    center_x, center_y = target.center

    candidates = [
        # Beside it, level with it.
        Rect.from_size(target.left - gap - width, center_y - height / 2, width, height),
        Rect.from_size(target.right + gap, center_y - height / 2, width, height),
        # Below and above.
        Rect.from_size(center_x - width / 2, target.bottom + gap, width, height),
        Rect.from_size(center_x - width / 2, target.top - gap - height, width, height),
        # Diagonals, for targets in a corner.
        Rect.from_size(target.left - gap - width, target.bottom + gap, width, height),
        Rect.from_size(target.right + gap, target.bottom + gap, width, height),
        Rect.from_size(target.left - gap - width, target.top - gap - height, width, height),
        Rect.from_size(target.right + gap, target.top - gap - height, width, height),
    ]

    # Sliding a candidate along the boundary edge can still leave the
    # target clear, so each is brought inside before being judged.
    adjusted = [keep_inside(candidate, bounds, restricted) for candidate in candidates]

    def acceptable(rect: Rect) -> bool:
        return (
            bounds.contains(rect)
            and rect.overlap_area(target) <= 0
            and all(rect.overlap_area(region) <= 0 for region in restricted)
        )

    origin = (current or adjusted[0]).center

    def distance(rect: Rect) -> float:
        x, y = rect.center

        return math.hypot(x - origin[0], y - origin[1])

    if current is not None:
        staying = keep_inside(
            Rect.from_size(current.left, current.top, width, height),
            bounds,
            restricted,
        )

        # Already beside it: do not move at all. "Beside" means close
        # enough that it is plain what she is pointing at; from across
        # the screen she walks over instead.
        dx = max(target.left - staying.right, staying.left - target.right, 0)
        dy = max(target.top - staying.bottom, staying.top - target.bottom, 0)

        if acceptable(staying) and math.hypot(dx, dy) <= height * NEAR:
            return Placement(staying, False)

    good = [rect for rect in adjusted if acceptable(rect)]

    if good:
        return Placement(min(good, key=distance), False)

    fallback = min(
        adjusted,
        key=lambda rect: (
            sum(rect.overlap_area(region) for region in restricted),
            rect.overlap_area(target),
            distance(rect),
        ),
    )

    return Placement(fallback, fallback.overlap_area(target) > 0)


def aim(origin: Tuple[float, float], target: Rect) -> Tuple[float, float]:
    """
    The point on a target's edge nearest to an origin: where a pointer
    drawn from the origin should end, so that it touches the target
    without crossing over its contents.
    """
    x = min(max(origin[0], target.left), target.right)
    y = min(max(origin[1], target.top), target.bottom)

    if (x, y) == (origin[0], origin[1]):
        return target.center

    return (x, y)
