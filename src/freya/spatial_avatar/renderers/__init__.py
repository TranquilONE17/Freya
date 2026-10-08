"""
Drawing backends for the avatar.

A renderer draws what an AvatarModel describes and reports what the
user does to her. It decides nothing about her behaviour: that lives
in the model, which is the same for every renderer.

A renderer runs inside the overlay process (overlay.py), never inside
Freya, so a renderer that crashes or hangs takes only the overlay with
it. To add one, write a class with the attributes below and add it to
RENDERERS; nothing else in Freya needs to change. Heavy renderers (a
3D engine, say) would normally live in their own process or program
and speak the same commands and events.
"""
import importlib
from typing import Dict, List, Optional, Tuple


class AvatarRenderer:
    """
    Base class for a renderer.

    id          short name used in settings and on the command line
    name        shown to the user
    cost        how demanding it is: 0 lightest. Used to pick a
                renderer that the machine can afford.
    needs_gpu   True when it will not run acceptably without one
    appearances the appearance ids it can draw
    """

    id = ""
    name = ""
    cost = 0
    needs_gpu = False
    appearances: Tuple[str, ...] = ()

    @classmethod
    def available(cls) -> Optional[str]:
        """
        None when the renderer can run here, otherwise a sentence
        saying why not (a missing optional dependency, for instance).
        """
        return None

    def read_layout(self):
        """
        The current display layout as this renderer sees it.
        """
        raise NotImplementedError

    def run(self, session) -> None:
        """
        Draw until the session says to stop. Each frame: call
        session.pump() and stop if it returns False, call
        session.model.tick(seconds), then draw session.model.frame().
        """
        raise NotImplementedError


# id -> (module, class). Imported only when chosen, so a renderer's
# dependencies are needed only by those who use it.
RENDERERS: Dict[str, Tuple[str, str]] = {
    "tk-placeholder": (
        "freya.spatial_avatar.renderers.tk_placeholder",
        "TkPlaceholderRenderer",
    ),
    "null": ("freya.spatial_avatar.renderers.null", "NullRenderer"),
}

DEFAULT_RENDERER = "tk-placeholder"


def load_renderer(renderer_id: str):
    """
    The renderer class with that id. Raises ValueError when it is
    unknown or cannot be loaded.
    """
    if renderer_id not in RENDERERS:
        raise ValueError(f"There is no avatar renderer called {renderer_id!r}.")

    module_name, class_name = RENDERERS[renderer_id]

    try:
        return getattr(importlib.import_module(module_name), class_name)
    except Exception as exc:
        raise ValueError(f"The {renderer_id} renderer could not be loaded: {exc}")


def choose_renderer(preferred: Optional[str] = None, gpu_available=False, max_cost=None):
    """
    Pick a renderer: the preferred one if it can run and is affordable,
    otherwise the most capable one that is. Returns (id, notes), where
    notes says why anything was passed over. Raises ValueError when
    nothing at all can run.
    """
    notes: List[str] = []
    order = ([preferred] if preferred in RENDERERS else []) + [
        renderer_id
        for renderer_id in RENDERERS
        if renderer_id not in (preferred, "null")
    ]
    usable = []

    for renderer_id in order:
        try:
            renderer = load_renderer(renderer_id)
        except ValueError as exc:
            notes.append(str(exc))
            continue

        problem = renderer.available()

        if problem:
            notes.append(f"{renderer.name}: {problem}")
        elif renderer.needs_gpu and not gpu_available:
            notes.append(f"{renderer.name} needs a graphics card.")
        elif max_cost is not None and renderer.cost > max_cost:
            notes.append(f"{renderer.name} is too demanding right now.")
        else:
            usable.append(renderer)

    if not usable:
        raise ValueError(
            "No avatar renderer can run here. " + " ".join(notes)
        )

    if preferred and usable[0].id == preferred:
        return preferred, notes

    return max(usable, key=lambda renderer: renderer.cost).id, notes
