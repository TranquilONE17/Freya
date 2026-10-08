"""
The vocabulary spoken between Freya and an avatar renderer.

Commands go to the renderer and events come back, each as one JSON
object. Nothing in them is specific to any drawing technology, so a
renderer can be replaced (a placeholder today, a 3D engine later, a
display on another device after that) without anything else changing.

Every message carries `v`, the protocol version. Unknown fields are
ignored, so fields can be added without breaking an older renderer;
a change that an older renderer could not safely ignore raises the
version.
"""
from freya.spatial_avatar import PROTOCOL_VERSION
from freya.spatial_avatar.animation import NORMAL


# -- animation commands -------------------------------------------------

MOVE_TO = "move_to"                  # x, y (virtual, top-left) [, seconds]
LOOK_AT = "look_at"                  # rect (virtual) or none to look ahead
POINT_AT = "point_at"                # rect (virtual), target_id [, reposition]
WAVE = "wave"
IDLE = "idle"                        # stop gestures, keep breathing
SET_EXPRESSION = "set_expression"    # expression
RESIZE = "resize"                    # percent of usable display height
SET_APPEARANCE = "set_appearance"    # appearance
RETURN_TO_REST = "return_to_rest"

ANIMATION_COMMANDS = (
    MOVE_TO,
    LOOK_AT,
    POINT_AT,
    WAVE,
    IDLE,
    SET_EXPRESSION,
    RESIZE,
    SET_APPEARANCE,
    RETURN_TO_REST,
)

# -- control commands ---------------------------------------------------

CONFIGURE = "configure"              # config: the whole settings object
SET_LAYOUT = "set_layout"            # layout: for renderers that cannot read it
SHOW = "show"
HIDE = "hide"
CANCEL = "cancel"                    # animation: id, or all
SPEECH = "speech"                    # phase: started|progress|completed|interrupted
REPORT = "report"                    # ask for a state event now
SHUTDOWN = "shutdown"

CONTROL_COMMANDS = (
    CONFIGURE,
    SET_LAYOUT,
    SHOW,
    HIDE,
    CANCEL,
    SPEECH,
    REPORT,
    SHUTDOWN,
)

COMMANDS = ANIMATION_COMMANDS + CONTROL_COMMANDS

# -- events from a renderer ---------------------------------------------

READY = "ready"                      # protocol, renderer, layout
STATE = "state"                      # the avatar's current state
ANIMATION = "animation"              # id, command, state
LAYOUT_CHANGED = "layout_changed"    # layout
USER_MOVED = "user_moved"            # the user dragged her: x, y, display
USER_RESIZED = "user_resized"        # the user resized her: percent
USER_SETTING = "user_setting"        # the user changed a setting: key, value
EXIT_REQUESTED = "exit_requested"    # the user chose Exit on the overlay
ERROR = "error"                      # text

SPEECH_PHASES = ("started", "progress", "completed", "interrupted")


def command(op: str, priority: int = NORMAL, **fields) -> dict:
    """
    Build a command message.
    """
    if op not in COMMANDS:
        raise ValueError(f"Unknown avatar command {op!r}.")

    return {"v": PROTOCOL_VERSION, "op": op, "priority": priority, **fields}


def event(kind: str, **fields) -> dict:
    return {"v": PROTOCOL_VERSION, "event": kind, **fields}


def compatible(message) -> bool:
    """
    Whether a message is in a version of the vocabulary this code
    speaks.
    """
    return isinstance(message, dict) and message.get("v") == PROTOCOL_VERSION
