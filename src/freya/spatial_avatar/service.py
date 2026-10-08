import threading
import time
from typing import Callable, List, Optional

from freya.core.capabilities import CapabilityDefinition
from freya.core.providers import ProviderDefinition
from freya.spatial_avatar import PROTOCOL_VERSION
from freya.spatial_avatar import commands as c
from freya.spatial_avatar.animation import NORMAL, USER
from freya.spatial_avatar.appearance import APPEARANCES, EXPRESSIONS
from freya.spatial_avatar.config import (
    LARGEST_PERCENT,
    SMALLEST_PERCENT,
    AvatarConfig,
    AvatarConfigStore,
)
from freya.spatial_avatar.geometry import (
    NORMALIZED,
    DisplayLayout,
    GeometryError,
    Rect,
    probe_layout,
    single_display_layout,
)
from freya.spatial_avatar.host import STOPPED, AvatarError, AvatarHost
from freya.spatial_avatar.renderers import choose_renderer
from freya.spatial_avatar.targets import (
    MockTargetProvider,
    TargetError,
    TargetRegistry,
    UserRegionProvider,
)


AVATAR_PROVIDER = "avatar-local"

# How long a layout read while the overlay is not running is reused.
LAYOUT_CACHE_SECONDS = 5.0

# -- permissions ------------------------------------------------------------
#
# Each is a separate capability name, so each is granted or withheld on
# its own by policy. Holding one never implies another: being allowed
# to point at something is not being allowed to click it.

AVATAR_DISPLAY = "avatar.display"            # show, move, resize, restyle her
SCREEN_GEOMETRY = "screen.geometry.read"     # sizes and positions of displays
AVATAR_POINT = "avatar.point"                # point at or outline a place

# Built in Phase 1. These are the only avatar capabilities that exist.
AVATAR_CAPABILITIES = [AVATAR_DISPLAY, SCREEN_GEOMETRY, AVATAR_POINT]

# Named now so that later phases have agreed names to ask for, and so
# that it is plain they are separate. NONE OF THESE IS BUILT: there is
# no code behind them, no capability registered, and no policy rule
# for them, so the broker refuses them like any unknown capability.
FUTURE_PERMISSIONS = {
    "screen.accessibility.read": "Read what programs report about their windows and controls",
    "screen.capture": "Capture what is shown on screen",
    "screen.analyze": "Analyse captured screen content",
    "input.mouse": "Move or click the mouse",
    "input.keyboard": "Type or press keys",
    "app.action": "Carry out an action in a program",
}

PERMISSION_NAMES = {
    AVATAR_DISPLAY: "Show and move the avatar",
    SCREEN_GEOMETRY: "Read the size and position of displays",
    AVATAR_POINT: "Point at or outline a place on screen",
}

DISPLAY_ACTIONS = (
    "show",
    "hide",
    "stop",
    "configure",
    "resize",
    "appearance",
    "expression",
    "move",
    "rest",
    "wave",
    "idle",
)


class AvatarService:
    """
    The avatar as Freya sees it: three capabilities, her settings, and
    the overlay that draws her.

    Everything Freya or her window asks of the avatar is a broker
    invocation, so it is checked against policy and written to the
    audit log like any other capability. The avatar has no other way
    in. It can show itself, learn the layout of the displays, and point
    at a place; it cannot see what is on the screen or send input to
    anything, because no such code exists here.

    What the user does directly to the overlay (dragging her, resizing
    her, hiding or closing her) is honoured without a policy check:
    it is the user acting, and they must always be able to move her out
    of the way or dismiss her.
    """

    def __init__(
        self,
        broker,
        user: str,
        store: Optional[AvatarConfigStore] = None,
        host: Optional[AvatarHost] = None,
        publish: Optional[Callable[..., None]] = None,
        renderer: Optional[str] = None,
        gpu_available: bool = False,
        probe: Optional[Callable[[], DisplayLayout]] = None,
    ):
        self._broker = broker
        self._user = user
        self._store = store or AvatarConfigStore()
        self._publish = publish or (lambda *args, **fields: None)
        self._lock = threading.RLock()
        self._commands = 0

        self.notes: List[str] = []
        self.error = ""

        if host is None:
            try:
                renderer, self.notes = choose_renderer(
                    renderer, gpu_available=gpu_available
                )
            except ValueError as exc:
                renderer = "null"
                self.error = str(exc)

            host = AvatarHost(renderer)

        self._host = host
        self._host._on_event = self._overlay_event

        self._probe = probe or probe_layout
        self._probed: Optional[DisplayLayout] = None
        self._probed_at = 0.0

        self.config = self._store.load(user)
        self._regions = UserRegionProvider()
        self.targets = TargetRegistry([MockTargetProvider(), self._regions])

    # -- registration ----------------------------------------------------------

    def provider(self) -> ProviderDefinition:
        return ProviderDefinition(
            provider_id=AVATAR_PROVIDER,
            name="Freya spatial avatar",
            capabilities=list(AVATAR_CAPABILITIES),
            start_handler=lambda: None,
            health_handler=lambda: True,
            metadata={"protocol": PROTOCOL_VERSION},
        )

    def capabilities(self) -> List[CapabilityDefinition]:
        return [
            CapabilityDefinition(
                name=AVATAR_DISPLAY,
                description=(
                    "Shows, hides, moves, resizes, or restyles Freya's "
                    "on-screen avatar. It displays only; it reads nothing "
                    "from the screen and sends no input."
                ),
                provider=AVATAR_PROVIDER,
                handler=self._display,
                category="avatar",
            ),
            CapabilityDefinition(
                name=SCREEN_GEOMETRY,
                description=(
                    "Returns the positions, sizes, usable areas, and scale "
                    "factors of the displays. It returns nothing that is "
                    "shown on them."
                ),
                provider=AVATAR_PROVIDER,
                handler=self._geometry,
                category="avatar",
            ),
            CapabilityDefinition(
                name=AVATAR_POINT,
                description=(
                    "Makes the avatar point at a place on screen: a "
                    "demonstration target or a region the user chose. "
                    "Pointing does not click, type, or change anything."
                ),
                provider=AVATAR_PROVIDER,
                handler=self._point,
                category="avatar",
            ),
        ]

    # -- the overlay -------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._host.running

    def layout(self) -> DisplayLayout:
        """
        The display layout: the overlay's view of it when it is
        running (it sees true pixel coordinates), otherwise read
        directly, otherwise a stand-in.
        """
        if self._host.layout is not None and self._host.running:
            return self._host.layout

        now = time.monotonic()

        if self._probed is None or now - self._probed_at > LAYOUT_CACHE_SECONDS:
            try:
                self._probed = self._probe()
            except GeometryError:
                self._probed = self._host.layout or single_display_layout()

            self._probed_at = now

        return self._probed

    def _send(self, op, priority=NORMAL, **fields) -> str:
        with self._lock:
            self._commands += 1
            command_id = f"c{self._commands}"

        if not self._host.send(c.command(op, priority, id=command_id, **fields)):
            raise AvatarError("The avatar is not running.")

        return command_id

    def _ensure_running(self) -> None:
        if self._host.running:
            return

        self._host.start()
        self._host.send(c.command(c.CONFIGURE, config=self.config.as_dict()))

    def _save(self, config: AvatarConfig, push=True) -> None:
        with self._lock:
            self.config = config
            self._store.save(self._user, config)

        if push and self._host.running:
            self._host.send(c.command(c.CONFIGURE, config=config.as_dict()))

    def stop(self) -> None:
        """
        Close the overlay. Used at shutdown and when the user asks.
        """
        self._host.stop()

    # -- capability handlers -----------------------------------------------------
    #
    # Reached only through the broker. Arguments are untrusted (they
    # may have come from the window or, later, from a model) and are
    # checked here and again by the avatar's model.

    def _display(self, action=None, value=None):
        if action not in DISPLAY_ACTIONS:
            raise AvatarError("That is not something the avatar can do.")

        if action == "stop":
            self._save(self.config.updated({"visible": False}), push=False)
            self._host.stop()
            return self.describe()

        if action == "hide":
            self._save(self.config.updated({"visible": False}))
            return self.describe()

        if action == "configure":
            self._save(self.config.updated(value))

            if self.config.visible:
                self._ensure_running()
                self._host.send(c.command(c.CONFIGURE, config=self.config.as_dict()))

            return self.describe()

        # Everything else needs her on screen.
        if not self.config.visible:
            self._save(self.config.updated({"visible": True}), push=False)

        self._ensure_running()
        self._host.send(c.command(c.CONFIGURE, config=self.config.as_dict()))

        if action == "resize":
            limits = self.config.size
            percent = limits.clamp(value)
            self._save(self.config.updated({"current_size": percent}), push=False)
            self._send(c.RESIZE, USER, percent=percent)
        elif action == "appearance":
            if value not in APPEARANCES:
                raise AvatarError("That appearance is not one the avatar has.")

            self._save(self.config.updated({"appearance": value}), push=False)
            self._send(c.SET_APPEARANCE, appearance=value)
        elif action == "expression":
            if value not in EXPRESSIONS:
                raise AvatarError("That expression is not one the avatar has.")

            self._send(c.SET_EXPRESSION, expression=value)
        elif action == "move":
            try:
                x, y = float(value["x"]), float(value["y"])
            except (TypeError, KeyError, ValueError):
                raise AvatarError("A move needs a position.")

            self._send(c.MOVE_TO, x=x, y=y)
        elif action == "rest":
            self._send(c.RETURN_TO_REST)
        elif action == "wave":
            self._send(c.WAVE)
        elif action == "idle":
            self._send(c.IDLE)

        return self.describe()

    def _geometry(self):
        return self.layout().as_dict()

    def _point(self, target_id=None, region=None, label=""):
        """
        Point at a known target, or at a region the user picked out.
        A region is {"display_id", "area"} with the area in 0..1 of
        that display's usable area.
        """
        layout = self.layout()

        if region is not None:
            try:
                display_id = region["display_id"]
                area = Rect.from_value(region["area"])
                rect = layout.rect_to_virtual(area, NORMALIZED, display_id)
            except (TypeError, KeyError, GeometryError):
                raise AvatarError("That region could not be read.")

            self.targets.refresh(layout)

            try:
                target_id = self._regions.add(rect, layout, label).target_id
            except TargetError as exc:
                raise AvatarError(str(exc))

        # Only providers whose kind of looking this capability covers
        # are asked. One that captured or read the screen would name a
        # different permission and would not be asked here.
        self.targets.refresh(
            layout, allowed=lambda provider: provider.permission == AVATAR_POINT
        )

        try:
            target = self.targets.resolve(target_id, layout)
        except TargetError as exc:
            raise AvatarError(str(exc))

        if not self.config.visible:
            self._save(self.config.updated({"visible": True}), push=False)

        self._ensure_running()
        self._host.send(c.command(c.CONFIGURE, config=self.config.as_dict()))
        self._send(
            c.POINT_AT,
            rect=target.rect.as_dict(),
            target_id=target.target_id,
        )

        return {"target": target.as_dict(), **self.describe()}

    # -- events from the overlay ----------------------------------------------

    def _overlay_event(self, message: dict) -> None:
        kind = message.get("event")

        if kind == c.USER_MOVED:
            self._remember_position(message)
        elif kind == c.USER_RESIZED:
            self._save(
                self.config.updated({"current_size": message.get("percent")}),
                push=False,
            )
        elif kind == c.USER_SETTING:
            key = message.get("key")

            # The user changed something on the overlay itself. Only
            # these settings can be changed that way.
            if key in ("click_through", "always_on_top", "visible", "appearance"):
                self._save(self.config.updated({key: message.get("value")}))
        elif kind == c.EXIT_REQUESTED:
            self._save(self.config.updated({"visible": False}), push=False)
            threading.Thread(target=self._host.stop, daemon=True).start()
        elif kind == c.LAYOUT_CHANGED:
            # Anything remembered about the old layout may be wrong.
            self.targets.invalidate()
        elif kind == STOPPED:
            self.targets.invalidate()

            if not message.get("expected"):
                self.error = (
                    "The avatar stopped unexpectedly. Freya is unaffected; "
                    "show the avatar again to restart it."
                )
        elif kind == c.ERROR:
            self.error = str(message.get("text") or "")[:300]
        elif kind == c.READY:
            self.error = ""

        if kind in (
            c.STATE,
            c.READY,
            STOPPED,
            c.ERROR,
            c.LAYOUT_CHANGED,
            c.USER_MOVED,
            c.USER_RESIZED,
            c.USER_SETTING,
            c.EXIT_REQUESTED,
        ):
            self._publish("avatar", state=self.describe())

    def _remember_position(self, message: dict) -> None:
        """
        Where the user dragged her becomes where she rests.
        """
        state = self._host.state or {}
        layout = self._host.layout
        display_id = message.get("display")

        if layout is None or not layout.has_display(display_id):
            return

        try:
            rect = Rect.from_value(state.get("rect"))
            rect = rect.moved_to(float(message["x"]), float(message["y"]))
        except (GeometryError, KeyError, TypeError, ValueError):
            return

        boundary = self.config.boundary_for(layout.display(display_id))

        if boundary.width <= 0 or boundary.height <= 0:
            return

        self._save(
            self.config.updated(
                {
                    "rest_display": display_id,
                    "rest_x": (rect.left + rect.width / 2 - boundary.left)
                    / boundary.width,
                    "rest_y": (rect.bottom - boundary.top) / boundary.height,
                }
            )
        )

    # -- speech (SpeechListener) -----------------------------------------------
    #
    # Called from the voice's thread. These only pass the news on; if
    # the avatar is not running they do nothing.

    def speech_started(self, text: str = "") -> None:
        self._host.send(c.command(c.SPEECH, phase="started"))

    def speech_progress(self, level: float = 0.6) -> None:
        self._host.send(c.command(c.SPEECH, phase="progress", level=level))

    def speech_completed(self) -> None:
        self._host.send(c.command(c.SPEECH, phase="completed"))

    def speech_interrupted(self) -> None:
        self._host.send(c.command(c.SPEECH, phase="interrupted"))

    # -- the window ----------------------------------------------------------------

    def describe(self) -> dict:
        """
        Everything the window's Avatar tab shows.
        """
        layout = self.layout()

        return {
            "protocol": PROTOCOL_VERSION,
            "running": self._host.running,
            "renderer": self._host.renderer,
            "config": self.config.as_dict(),
            "state": self._host.state,
            "displays": [display.as_dict() for display in layout.displays],
            "appearances": [
                {"id": a.id, "name": a.name, "summary": a.summary}
                for a in APPEARANCES.values()
            ],
            "expressions": list(EXPRESSIONS),
            "size_range": {"smallest": SMALLEST_PERCENT, "largest": LARGEST_PERCENT},
            "targets": [
                {
                    "id": name,
                    "label": label,
                }
                for name, (label, _) in MockTargetProvider.SPOTS.items()
            ],
            "permissions": [
                {"id": name, "name": text, "built": True}
                for name, text in PERMISSION_NAMES.items()
            ]
            + [
                {"id": name, "name": text, "built": False}
                for name, text in FUTURE_PERMISSIONS.items()
            ],
            "notes": list(self.notes),
            "error": self.error,
        }

    def handle(self, message: dict) -> dict:
        """
        Carry out one request from the window's Avatar tab. Every
        request that does anything goes through the broker; a refusal
        or failure comes back as an error message, never an exception.
        """
        error = None
        action = message.get("action") if isinstance(message, dict) else None

        try:
            if action == "state":
                pass
            elif action == "point":
                display_id = message.get("display")
                target = message.get("target")
                result = self._broker.invoke(
                    AVATAR_POINT,
                    target_id=(
                        f"mock:{display_id}:{target}" if target is not None else None
                    ),
                    region=message.get("region"),
                )
                error = None if result.success else result.error
            elif action in DISPLAY_ACTIONS:
                result = self._broker.invoke(
                    AVATAR_DISPLAY,
                    action=action,
                    value=message.get("value"),
                )
                error = None if result.success else result.error
            else:
                error = "The Avatar tab asked for something unknown."
        except Exception as exc:
            error = f"That did not work: {exc}"

        return {"state": self.describe(), "error": error}
