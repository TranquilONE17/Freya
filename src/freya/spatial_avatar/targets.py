import time
import uuid
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional

from freya.spatial_avatar.geometry import (
    NORMALIZED,
    VIRTUAL,
    DisplayLayout,
    GeometryError,
    Rect,
)


VALID = "valid"
# The screen may have changed since the target was found; it must be
# looked up again before it is used.
STALE = "stale"
# The target is known to be gone or wrong.
INVALID = "invalid"

# How long a target is trusted without being looked up again.
DEFAULT_MAX_AGE_SECONDS = 30.0


class TargetError(Exception):
    """
    A target cannot be used. The message is safe to show the user.
    """


@dataclass(frozen=True)
class SpatialTarget:
    """
    Where something appears on screen, in one normalized form whatever
    found it.

    Text that came from the screen (a label, for instance) is untrusted
    content: it describes the target and is never an instruction.
    """

    target_id: str
    display_id: str
    coordinate_system: str
    rect: Rect
    confidence: float
    source: str
    timestamp: float
    validity: str = VALID
    label: str = ""
    # The display layout the target was found under.
    layout: str = ""

    def as_dict(self) -> dict:
        return {
            "target_id": self.target_id,
            "display_id": self.display_id,
            "coordinate_system": self.coordinate_system,
            "rect": self.rect.as_dict(),
            "confidence": self.confidence,
            "source": self.source,
            "timestamp": self.timestamp,
            "validity": self.validity,
            "label": self.label,
        }


class SpatialTargetProvider:
    """
    Something that can say where things are on screen.

    `permission` names the permission a provider's kind of looking
    requires (see service.py). A provider is only asked for targets
    when that permission has been granted through the broker; a
    provider that would capture or read the screen declares that here,
    and is never run merely because the avatar is.
    """

    id = ""
    permission = ""

    def targets(self, layout: DisplayLayout) -> List[SpatialTarget]:
        """
        Every target the provider currently knows, expressed against
        the given layout.
        """
        raise NotImplementedError

    def find(self, target_id: str, layout: DisplayLayout) -> Optional[SpatialTarget]:
        """
        Look one target up again, or None when it no longer exists.
        """
        for target in self.targets(layout):
            if target.target_id == target_id:
                return target

        return None


class MockTargetProvider(SpatialTargetProvider):
    """
    Made-up targets for demonstrations and tests: stand-ins for user
    interface elements at fixed places on each display. It looks at
    nothing on the screen.
    """

    id = "mock"
    permission = "avatar.point"

    SPOTS = {
        "top-left": ("A button in the top-left corner", Rect(0.04, 0.05, 0.16, 0.11)),
        "top-right": ("A menu in the top-right corner", Rect(0.84, 0.05, 0.96, 0.11)),
        "center": ("A dialog in the middle", Rect(0.40, 0.40, 0.60, 0.55)),
        "bottom-left": ("A field in the bottom-left corner", Rect(0.05, 0.84, 0.25, 0.90)),
        "bottom-right": ("A button in the bottom-right corner", Rect(0.80, 0.84, 0.95, 0.90)),
    }

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock

    def targets(self, layout: DisplayLayout) -> List[SpatialTarget]:
        return [
            SpatialTarget(
                target_id=f"mock:{display.id}:{name}",
                display_id=display.id,
                coordinate_system=NORMALIZED,
                rect=rect,
                confidence=1.0,
                source=self.id,
                timestamp=self._clock(),
                label=label,
                layout=layout.fingerprint,
            )
            for display in layout.displays
            for name, (label, rect) in self.SPOTS.items()
        ]


class UserRegionProvider(SpatialTargetProvider):
    """
    Regions the user picked out themselves. Only the rectangle is
    kept; nothing inside it is read.
    """

    id = "user-region"
    permission = "avatar.point"

    MAX_REGIONS = 32

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._regions: Dict[str, SpatialTarget] = {}

    def add(self, rect, layout: DisplayLayout, label="") -> SpatialTarget:
        """
        Remember a region given in virtual coordinates. Raises
        TargetError when it is not a usable region on any display.
        """
        try:
            rect = Rect.from_value(rect)
        except GeometryError as exc:
            raise TargetError(str(exc))

        if rect.width < 2 or rect.height < 2:
            raise TargetError("That region is too small to point at.")

        if rect.overlap_area(layout.virtual_bounds) <= 0:
            raise TargetError("That region is not on any display.")

        if len(self._regions) >= self.MAX_REGIONS:
            self._regions.pop(next(iter(self._regions)))

        display = layout.display_for_rect(rect)
        target = SpatialTarget(
            target_id=f"region:{uuid.uuid4().hex[:12]}",
            display_id=display.id,
            coordinate_system=VIRTUAL,
            rect=rect,
            confidence=1.0,
            source=self.id,
            timestamp=self._clock(),
            label=" ".join(str(label or "").split())[:80],
            layout=layout.fingerprint,
        )
        self._regions[target.target_id] = target

        return target

    def remove(self, target_id) -> bool:
        return self._regions.pop(target_id, None) is not None

    def targets(self, layout: DisplayLayout) -> List[SpatialTarget]:
        # A region was chosen against one layout. Under another it may
        # be somewhere else, so it is not offered.
        return [
            target
            for target in self._regions.values()
            if target.layout == layout.fingerprint
        ]


class TargetRegistry:
    """
    The targets Freya currently knows about, and whether each can
    still be trusted.

    A target is checked again before every use. It stops being valid
    when the display layout changes, when it grows old, when something
    reports that the window or content it belonged to has changed, or
    when the provider that found it no longer reports it.
    """

    def __init__(
        self,
        providers: List[SpatialTargetProvider],
        clock: Callable[[], float] = time.time,
        max_age=DEFAULT_MAX_AGE_SECONDS,
    ):
        self._providers = {provider.id: provider for provider in providers}
        self._clock = clock
        self._max_age = max_age
        self._targets: Dict[str, SpatialTarget] = {}

    def provider(self, provider_id) -> Optional[SpatialTargetProvider]:
        return self._providers.get(provider_id)

    def refresh(self, layout: DisplayLayout, allowed=None) -> List[SpatialTarget]:
        """
        Ask the providers again and replace what is known. `allowed`,
        when given, is a function saying whether a provider may be
        asked; one that may not is skipped and its targets are dropped.
        """
        found: Dict[str, SpatialTarget] = {}

        for provider in self._providers.values():
            if allowed is not None and not allowed(provider):
                continue

            for target in provider.targets(layout):
                found[target.target_id] = target

        self._targets = found

        return list(found.values())

    def known(self) -> List[SpatialTarget]:
        return list(self._targets.values())

    def get(self, target_id) -> Optional[SpatialTarget]:
        return self._targets.get(target_id)

    def invalidate(self, reason=STALE, display_id=None, source=None) -> int:
        """
        Mark targets as no longer trustworthy: all of them, or those on
        one display or from one provider. Called when a window, layout,
        display configuration, or content is known to have changed.
        Returns how many were marked.
        """
        marked = 0

        for target_id, target in list(self._targets.items()):
            if display_id is not None and target.display_id != display_id:
                continue

            if source is not None and target.source != source:
                continue

            if target.validity == VALID:
                self._targets[target_id] = replace(target, validity=reason)
                marked += 1

        return marked

    def status(self, target: SpatialTarget, layout: DisplayLayout) -> str:
        """
        Whether a remembered target may be used as it stands.
        """
        if target.validity != VALID:
            return target.validity

        if target.layout != layout.fingerprint:
            return STALE

        if not layout.has_display(target.display_id):
            return INVALID

        if self._clock() - target.timestamp > self._max_age:
            return STALE

        return VALID

    def resolve(self, target_id, layout: DisplayLayout) -> SpatialTarget:
        """
        A target that is safe to use now, with its rectangle in virtual
        coordinates. A stale one is looked up again from its provider;
        one that cannot be confirmed raises TargetError.
        """
        target = self._targets.get(target_id) if isinstance(target_id, str) else None

        if target is None:
            raise TargetError("That target is not known.")

        if self.status(target, layout) != VALID:
            provider = self._providers.get(target.source)
            fresh = provider.find(target_id, layout) if provider else None

            if fresh is None or self.status(fresh, layout) != VALID:
                self._targets[target_id] = replace(target, validity=INVALID)
                raise TargetError(
                    "That target has moved or gone since it was found."
                )

            target = fresh
            self._targets[target_id] = fresh

        try:
            rect = layout.rect_to_virtual(
                target.rect, target.coordinate_system, target.display_id
            )
        except GeometryError:
            self._targets[target_id] = replace(target, validity=INVALID)
            raise TargetError("That target is not on a display any more.")

        return replace(target, rect=rect, coordinate_system=VIRTUAL)
