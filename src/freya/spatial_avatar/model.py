import math
from typing import Callable, Optional

from freya.spatial_avatar import commands as c
from freya.spatial_avatar.animation import (
    IDLE,
    NORMAL,
    USER,
    Animation,
    Animator,
)
from freya.spatial_avatar.appearance import (
    APPEARANCES,
    DEFAULT_EXPRESSION,
    EXPRESSIONS,
)
from freya.spatial_avatar.config import AvatarConfig
from freya.spatial_avatar.geometry import DisplayLayout, GeometryError, Rect
from freya.spatial_avatar.placement import aim, keep_inside, place_beside


# Channels: the parts of the avatar that animate independently.
BODY = "body"        # where she is
SIZE = "size"        # how big she is
ARM = "arm"          # pointing and waving
BREATH = "breath"    # the slight idle motion

# Pixels per second she moves at, and the limits on how long a move may
# take however near or far.
MOVE_SPEED = 1400.0
MOVE_SHORTEST = 0.25
MOVE_LONGEST = 1.2

RESIZE_SECONDS = 0.35
ARM_SECONDS = 0.3
WAVE_SECONDS = 1.6
BREATH_SECONDS = 4.0


class AvatarModel:
    """
    The avatar's state, and what each command does to it.

    This is the whole behaviour of the avatar with no drawing in it. A
    renderer owns one of these, feeds it commands, calls tick() once a
    frame, and draws whatever frame() describes. That keeps every
    renderer's behaviour identical and lets all of it be tested without
    opening a window.

    Two rules hold whatever is asked: her size is always within the
    user's limits for the display she is on, and she is always inside
    the user's boundary for that display.
    """

    def __init__(
        self,
        layout: DisplayLayout,
        config: Optional[AvatarConfig] = None,
        emit: Optional[Callable[[dict], None]] = None,
    ):
        self.layout = layout
        self.config = config or AvatarConfig()
        self._emit = emit or (lambda message: None)
        self.animator = Animator(on_change=self._animation_changed)

        self.visible = self.config.visible
        self.appearance = self.config.appearance
        self.expression = DEFAULT_EXPRESSION
        self.speaking = False
        self.speech_level = 0.0

        self.display_id = self._rest_display().id
        self.size_percent = self.config.size_percent(self.display_id)
        self.rect = self.rest_rect()

        self.gaze: Optional[Rect] = None
        self.point_target: Optional[Rect] = None
        self.point_target_id: Optional[str] = None
        self.point_amount = 0.0
        self.covers_target = False
        self.wave_phase: Optional[float] = None
        self.breath = 0.0

        self._start_breathing()

    # -- events ------------------------------------------------------------

    def _animation_changed(self, animation: Animation) -> None:
        if animation.label:
            self._emit(
                c.event(
                    c.ANIMATION,
                    id=animation.label,
                    state=animation.state,
                    channel=animation.channel,
                )
            )

    def _start_breathing(self) -> None:
        def breathe(progress):
            self.breath = math.sin(progress * 2 * math.pi)

        self.animator.play(
            Animation(BREATH, BREATH_SECONDS, breathe, priority=IDLE, loop=True)
        )

    # -- where she may be, and how big -----------------------------------

    def _rest_display(self):
        wanted = self.config.rest_display

        if wanted and self.layout.has_display(wanted):
            return self.layout.display(wanted)

        return self.layout.primary

    def _display(self):
        if self.layout.has_display(self.display_id):
            return self.layout.display(self.display_id)

        return self._rest_display()

    def _fit(self, rect: Rect, display=None) -> Rect:
        """
        A rectangle brought inside the boundary of the display it is
        (mostly) on, clear of restricted regions, at the size allowed
        there. Everything that moves or resizes her goes through this.
        """
        display = display or self.layout.display_for_rect(rect)
        width, height = self.config.size_pixels(display, self.size_percent)

        # Keep her feet where they were while the size is corrected.
        feet_x = rect.left + rect.width / 2
        sized = Rect.from_size(feet_x - width / 2, rect.bottom - height, width, height)

        return keep_inside(
            sized,
            self.config.boundary_for(display),
            self.config.restricted_for(display),
        )

    def _place(self, rect: Rect, display=None) -> None:
        display = display or self.layout.display_for_rect(rect)
        self.size_percent = self.config.size_percent(display.id, self.size_percent)
        self.rect = self._fit(rect, display)
        self.display_id = display.id

    def rest_rect(self) -> Rect:
        display = self._rest_display()
        boundary = self.config.boundary_for(display)
        width, height = self.config.size_pixels(
            display, getattr(self, "size_percent", None)
        )
        feet_x = boundary.left + boundary.width * self.config.rest_x
        feet_y = boundary.top + boundary.height * self.config.rest_y

        return keep_inside(
            Rect.from_size(feet_x - width / 2, feet_y - height, width, height),
            boundary,
            self.config.restricted_for(display),
        )

    # -- settings and layout ---------------------------------------------

    def configure(self, config: AvatarConfig) -> None:
        """
        Apply new settings while running. Size and position are
        corrected at once if the new limits or boundaries require it.
        """
        resting = self.rect == self.rest_rect()
        self.config = config
        self.visible = config.visible

        if config.appearance in APPEARANCES:
            self.appearance = config.appearance

        if config.current_size is not None:
            self.size_percent = config.current_size
        elif config.auto_scale:
            self.size_percent = config.limits_for(self.display_id).preferred

        self.size_percent = config.size_percent(self.display_id, self.size_percent)

        if resting:
            self.rect = self.rest_rect()
            self.display_id = self._rest_display().id
        else:
            self._place(self.rect, self._display())

    def set_layout(self, layout: DisplayLayout) -> None:
        """
        The displays changed. Anything aimed at the old layout is
        dropped, and she is brought back onto a display that exists.
        """
        changed = layout.fingerprint != self.layout.fingerprint
        self.layout = layout

        if not changed:
            return

        self.animator.cancel_all(BODY)
        self._stop_pointing(immediately=True)

        if layout.has_display(self.display_id):
            self._place(self.rect, layout.display(self.display_id))
        else:
            self.display_id = self._rest_display().id
            self.size_percent = self.config.size_percent(self.display_id)
            self.rect = self.rest_rect()

    # -- direct manipulation by the user -----------------------------------

    def drag_to(self, left, top) -> None:
        """
        The user is dragging her. This wins over any movement she was
        making on her own.
        """
        self.animator.cancel_all(BODY)
        self._stop_pointing(immediately=True)
        self._place(self.rect.moved_to(left, top))

    def user_resize(self, percent) -> float:
        """
        The user resized her by hand. Returns the size she ended at,
        which is the request brought inside the limits.
        """
        self.animator.cancel_all(SIZE)
        self.size_percent = self.config.size_percent(self.display_id, percent)
        self._place(self.rect, self._display())

        return self.size_percent

    # -- commands ------------------------------------------------------------

    def _seconds(self, seconds: float) -> float:
        return seconds if self.config.smooth else 0.0

    def _move(self, destination: Rect, display, priority, label="") -> Animation:
        start = self.rect
        end = self._fit(destination, display)
        distance = math.hypot(end.left - start.left, end.bottom - start.bottom)
        seconds = min(max(distance / MOVE_SPEED, MOVE_SHORTEST), MOVE_LONGEST)

        if distance < 1:
            seconds = 0.0

        def step(progress):
            # Her feet travel in a straight line; the size follows the
            # display she is over.
            feet_x = (start.left + start.width / 2) + (
                (end.left + end.width / 2) - (start.left + start.width / 2)
            ) * progress
            feet_y = start.bottom + (end.bottom - start.bottom) * progress

            if progress >= 1.0:
                self._place(end, display)
            else:
                # Every point along the way is held to the same rules
                # as the destination: inside a boundary, out of
                # restricted regions.
                self._place(
                    Rect.from_size(
                        feet_x - self.rect.width / 2,
                        feet_y - self.rect.height,
                        self.rect.width,
                        self.rect.height,
                    )
                )

        return self.animator.play(
            Animation(BODY, self._seconds(seconds), step, priority, label)
        )

    def _raise_arm(self, toward: float, priority, label="", on_end=None) -> Animation:
        start = self.point_amount

        def step(progress):
            self.point_amount = start + (toward - start) * progress

        return self.animator.play(
            Animation(ARM, self._seconds(ARM_SECONDS), step, priority, label, on_end=on_end)
        )

    def _stop_pointing(self, immediately=False, priority=NORMAL) -> None:
        self.gaze = None
        self.wave_phase = None
        self.covers_target = False

        if immediately or self.point_amount <= 0:
            self.animator.cancel_all(ARM)
            self.point_amount = 0.0
            self.point_target = None
            self.point_target_id = None
            return

        def lowered(state):
            if self.point_amount <= 0.01:
                self.point_target = None
                self.point_target_id = None

        self._raise_arm(0.0, priority, on_end=lowered)

    def apply(self, message: dict) -> Optional[Animation]:
        """
        Carry out one command. Returns the animation it started, if
        any. Raises ValueError for a command that makes no sense; the
        avatar's state is unchanged when it does.
        """
        if not c.compatible(message):
            raise ValueError("That command is in a version I do not speak.")

        op = message.get("op")
        priority = message.get("priority", NORMAL)
        label = str(message.get("id") or "")

        if isinstance(priority, bool) or not isinstance(priority, int):
            priority = NORMAL

        if op == c.MOVE_TO:
            try:
                left, top = float(message["x"]), float(message["y"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("move_to needs x and y.")

            self._stop_pointing(priority=priority)

            return self._move(self.rect.moved_to(left, top), None, priority, label)

        if op == c.RETURN_TO_REST:
            self._stop_pointing(priority=priority)

            return self._move(self.rest_rect(), self._rest_display(), priority, label)

        if op == c.LOOK_AT:
            self.gaze = self._rect(message.get("rect"), optional=True)
            return None

        if op == c.POINT_AT:
            return self._point_at(message, priority, label)

        if op == c.WAVE:
            self._stop_pointing(immediately=True)

            def wave(progress):
                self.wave_phase = progress

            def finished(state):
                self.wave_phase = None

            return self.animator.play(
                Animation(
                    ARM, self._seconds(WAVE_SECONDS), wave, priority, label, on_end=finished
                )
            )

        if op == c.IDLE:
            self._stop_pointing(priority=priority)
            return None

        if op == c.SET_EXPRESSION:
            expression = message.get("expression")

            if expression not in EXPRESSIONS:
                raise ValueError("That expression is not one I have.")

            self.expression = expression
            return None

        if op == c.SET_APPEARANCE:
            appearance = message.get("appearance")

            if appearance not in APPEARANCES:
                raise ValueError("That appearance is not one I have.")

            self.appearance = appearance
            return None

        if op == c.RESIZE:
            return self._resize(message.get("percent"), priority, label)

        if op == c.SHOW:
            self.visible = True
            return None

        if op == c.HIDE:
            self.visible = False
            return None

        if op == c.CANCEL:
            wanted = message.get("animation")

            if wanted in (None, "all"):
                self.animator.cancel_all(below=USER + 1)
                self._start_breathing()
            else:
                for animation in self.animator.active():
                    if animation.label == str(wanted):
                        self.animator.cancel(animation)

            return None

        if op == c.SPEECH:
            phase = message.get("phase")

            if phase not in c.SPEECH_PHASES:
                raise ValueError("That is not a phase of speech.")

            self.speaking = phase in ("started", "progress")
            level = message.get("level")
            self.speech_level = (
                min(max(float(level), 0.0), 1.0)
                if isinstance(level, (int, float)) and not isinstance(level, bool)
                else (0.6 if self.speaking else 0.0)
            )
            return None

        raise ValueError(f"I do not know the avatar command {op!r}.")

    def _rect(self, value, optional=False) -> Optional[Rect]:
        if value is None and optional:
            return None

        try:
            return Rect.from_value(value)
        except GeometryError as exc:
            raise ValueError(str(exc))

    def _resize(self, percent, priority, label) -> Animation:
        if isinstance(percent, bool) or not isinstance(percent, (int, float)):
            raise ValueError("resize needs a size.")

        start = self.size_percent
        # The request is brought inside the limits before anything
        # moves, so she never even passes through a forbidden size.
        end = self.config.size_percent(self.display_id, percent)

        def step(progress):
            self.size_percent = start + (end - start) * progress
            self._place(self.rect, self._display())

        return self.animator.play(
            Animation(SIZE, self._seconds(RESIZE_SECONDS), step, priority, label)
        )

    def _point_at(self, message, priority, label) -> Animation:
        target = self._rect(message.get("rect"))

        if target.overlap_area(self.layout.virtual_bounds) <= 0:
            raise ValueError("That target is not on any display.")

        display = self.layout.display_for_rect(target)
        self.wave_phase = None
        self.point_target = target
        self.point_target_id = (
            str(message["target_id"])[:120] if message.get("target_id") else None
        )
        self.gaze = target

        if message.get("reposition", True) is not False:
            placement = place_beside(
                target,
                self.config.size_pixels(display, self.size_percent),
                self.config.boundary_for(display),
                self.config.restricted_for(display),
                current=self.rect if display.id == self.display_id else None,
            )
            self.covers_target = placement.covers_target
            self._move(placement.rect, display, priority)
        else:
            self.covers_target = self.rect.overlap_area(target) > 0

        return self._raise_arm(1.0, priority, label)

    # -- every frame -----------------------------------------------------------

    def tick(self, seconds: float) -> None:
        self.animator.tick(seconds)

    def moving(self) -> bool:
        """
        True while she needs a full frame rate: something is animating
        or she is speaking.
        """
        return self.speaking or self.animator.busy()

    def _shoulder(self):
        return (
            self.rect.left + self.rect.width / 2,
            self.rect.top + self.rect.height * 0.42,
        )

    def frame(self) -> dict:
        """
        Everything a renderer needs to draw this frame.
        """
        pointer = None

        if self.point_target is not None and self.point_amount > 0:
            origin = self._shoulder()
            tip = aim(origin, self.point_target)
            pointer = {
                "from": origin,
                "to": tip,
                "amount": self.point_amount,
                "target": self.point_target,
            }

        return {
            "visible": self.visible,
            "rect": self.rect,
            "display": self.display_id,
            "appearance": APPEARANCES[self.appearance],
            "expression": self.expression,
            "speaking": self.speaking,
            "speech_level": self.speech_level,
            "breath": self.breath,
            "gaze": self.gaze.center if self.gaze is not None else None,
            "pointer": pointer,
            "wave": self.wave_phase,
        }

    def state(self) -> dict:
        """
        Her state as plain data, for events and for the window.
        """
        return {
            "visible": self.visible,
            "rect": self.rect.as_dict(),
            "display": self.display_id,
            "size_percent": round(self.size_percent, 2),
            "appearance": self.appearance,
            "expression": self.expression,
            "speaking": self.speaking,
            "pointing_at": (
                self.point_target.as_dict() if self.point_target is not None else None
            ),
            "pointing_target_id": self.point_target_id,
            "pointing": round(self.point_amount, 2),
            "covers_target": self.covers_target,
            "waving": self.wave_phase is not None,
            "moving": self.animator.busy(),
        }
