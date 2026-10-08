"""
The avatar overlay: a separate program that draws the avatar.

    python -m freya.spatial_avatar.overlay --renderer tk-placeholder

It is started by Freya (host.py) but shares nothing with her except
two pipes: commands arrive on standard input, one JSON object per
line, and events leave on standard output the same way. It imports
none of Freya Core, opens none of her data, and has no way to invoke a
capability. If it crashes, Freya carries on; if Freya goes away, its
input closes and it exits.

It draws, and it reads the layout of the displays so that it can draw
in the right place. It does not capture the screen, read other
programs' windows, or send any input to them.
"""
import argparse
import json
import queue
import sys
import threading
import time

from freya.spatial_avatar import PROTOCOL_VERSION
from freya.spatial_avatar import commands as c
from freya.spatial_avatar.config import AvatarConfig
from freya.spatial_avatar.geometry import DisplayLayout, GeometryError
from freya.spatial_avatar.model import AvatarModel
from freya.spatial_avatar.renderers import load_renderer


# How often a state event is sent while she is moving, at most.
STATE_INTERVAL_SECONDS = 0.15
# How often commands are looked for while nothing is being drawn.
HIDDEN_INTERVAL_SECONDS = 0.1


class Session:
    """
    What a renderer works with: the avatar's model, the commands that
    have arrived, and a way to send events back.
    """

    def __init__(self, layout: DisplayLayout, events, incoming=None):
        self._events = events
        self._incoming = incoming if incoming is not None else queue.Queue()
        self._lock = threading.Lock()
        self._last_state = None
        self._last_state_time = 0.0
        self.running = True
        # Called by a renderer when settings arrive, so it can apply
        # the ones only it knows about (always-on-top, click-through).
        self.on_configure = lambda config: None
        self.model = AvatarModel(layout, AvatarConfig(), emit=self.emit)

    # -- events ----------------------------------------------------------------

    def emit(self, message: dict) -> None:
        with self._lock:
            try:
                self._events.write(json.dumps(message) + "\n")
                self._events.flush()
            except (OSError, ValueError):
                # Nobody is listening any more.
                self.running = False

    def report_state(self, force=False) -> None:
        state = self.model.state()
        now = time.monotonic()

        if state == self._last_state and not force:
            return

        if (
            not force
            and state["moving"]
            and now - self._last_state_time < STATE_INTERVAL_SECONDS
        ):
            return

        self._last_state = state
        self._last_state_time = now
        self.emit(c.event(c.STATE, state=state))

    # -- commands --------------------------------------------------------------

    def put(self, message) -> None:
        self._incoming.put(message)

    def read_commands(self, stream) -> None:
        """
        Read commands until the stream closes, which means whoever
        started the overlay has gone and it should stop too.
        """
        for line in stream:
            line = line.strip()

            if not line:
                continue

            try:
                self._incoming.put(json.loads(line))
            except ValueError:
                self.emit(c.event(c.ERROR, text="A command could not be read."))

        self._incoming.put(c.command(c.SHUTDOWN))

    def _handle(self, message) -> None:
        if not c.compatible(message):
            self.emit(
                c.event(c.ERROR, text="A command was in a version I do not speak.")
            )
            return

        op = message.get("op")

        if op == c.SHUTDOWN:
            self.running = False
        elif op == c.CONFIGURE:
            config = AvatarConfig.from_value(message.get("config"))
            self.model.configure(config)
            self.on_configure(config)
        elif op == c.SET_LAYOUT:
            try:
                self.set_layout(DisplayLayout.from_value(message.get("layout")))
            except GeometryError as exc:
                self.emit(c.event(c.ERROR, text=str(exc)))
        elif op == c.REPORT:
            self.report_state(force=True)
        else:
            try:
                self.model.apply(message)
            except ValueError as exc:
                self.emit(
                    c.event(c.ERROR, text=str(exc), id=str(message.get("id") or ""))
                )

    def set_layout(self, layout: DisplayLayout) -> None:
        if layout.fingerprint == self.model.layout.fingerprint:
            return

        self.model.set_layout(layout)
        self.emit(c.event(c.LAYOUT_CHANGED, layout=layout.as_dict()))

    def pump(self) -> bool:
        """
        Carry out the commands that have arrived. Returns False when
        the overlay should stop.
        """
        while self.running:
            try:
                message = self._incoming.get_nowait()
            except queue.Empty:
                break

            self._handle(message)

        self.report_state()

        return self.running

    def frame_interval(self) -> float:
        """
        Seconds until the next frame is worth drawing: the full rate
        while she is moving or speaking, a slow one while she is idle,
        and no drawing at all while she is hidden.
        """
        config = self.model.config

        if not self.model.visible:
            return HIDDEN_INTERVAL_SECONDS

        if self.model.moving():
            return 1.0 / config.fps_limit

        return 1.0 / min(config.idle_fps, config.fps_limit)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Freya's avatar overlay.")
    parser.add_argument("--renderer", default="tk-placeholder")
    parser.add_argument(
        "--fail",
        action="store_true",
        help="fail while drawing, to test that Freya survives it",
    )
    arguments = parser.parse_args(argv)

    # Keep the real output for events and send anything else that gets
    # printed to the error stream, so a stray print cannot corrupt one.
    events = sys.stdout
    sys.stdout = sys.stderr

    try:
        renderer = load_renderer(arguments.renderer)()
    except ValueError as exc:
        events.write(json.dumps(c.event(c.ERROR, text=str(exc))) + "\n")
        events.flush()
        return 2

    problem = renderer.available()

    if problem:
        events.write(json.dumps(c.event(c.ERROR, text=problem)) + "\n")
        events.flush()
        return 2

    try:
        layout = renderer.read_layout()
    except GeometryError as exc:
        events.write(json.dumps(c.event(c.ERROR, text=str(exc))) + "\n")
        events.flush()
        return 2

    session = Session(layout, events)
    sys.stdin.reconfigure(encoding="utf-8")
    threading.Thread(
        target=session.read_commands,
        args=(sys.stdin,),
        name="AvatarCommands",
        daemon=True,
    ).start()

    session.emit(
        c.event(
            c.READY,
            protocol=PROTOCOL_VERSION,
            renderer=renderer.id,
            appearances=list(renderer.appearances),
            layout=layout.as_dict(),
        )
    )

    if arguments.fail:
        raise RuntimeError("The renderer failed, as it was asked to.")

    renderer.run(session)

    return 0


if __name__ == "__main__":
    sys.exit(main())
