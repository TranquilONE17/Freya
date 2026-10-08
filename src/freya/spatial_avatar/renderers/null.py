import time

from freya.spatial_avatar.geometry import single_display_layout
from freya.spatial_avatar.renderers import AvatarRenderer


class NullRenderer(AvatarRenderer):
    """
    Draws nothing. It runs the avatar's real behaviour with no window,
    for tests and for machines with no display to draw on.
    """

    id = "null"
    name = "No display"
    cost = 0
    appearances = ("lightweight", "realistic", "holographic")

    def read_layout(self):
        return single_display_layout()

    def run(self, session) -> None:
        last = time.perf_counter()

        while session.pump():
            now = time.perf_counter()
            session.model.tick(now - last)
            last = now
            time.sleep(session.frame_interval())
