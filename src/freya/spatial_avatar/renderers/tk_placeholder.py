import math
import os
import time

from freya.spatial_avatar import commands as c
from freya.spatial_avatar.appearance import APPEARANCES
from freya.spatial_avatar.geometry import (
    GeometryError,
    enable_dpi_awareness,
    read_windows_layout,
    single_display_layout,
)
from freya.spatial_avatar.renderers import AvatarRenderer


# A colour that is never drawn with: Windows shows whatever is behind
# the window wherever a pixel has exactly this colour.
CLEAR = "#010203"

LAYOUT_CHECK_SECONDS = 2.0
WHEEL_STEP_PERCENT = 2.0
HANDLE_SIZE = 26

# Window styles, set through the Windows API because tkinter has no
# name for them.
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020   # mouse input passes through
WS_EX_TOOLWINDOW = 0x00000080    # no taskbar button
WS_EX_NOACTIVATE = 0x08000000    # clicking it does not take focus


class TkPlaceholderRenderer(AvatarRenderer):
    """
    A simple drawn figure in a transparent window that stays above
    other windows. It is a stand-in for a real character: enough to
    show her moving, resizing, changing appearance, and pointing.

    Three small windows, none of which takes keyboard focus:

      body     the figure. Drag it to move her, right-click for the
               menu, roll the wheel to resize. In click-through mode
               the mouse passes straight through it.
      handle   a small button beside her that always accepts clicks,
               even in click-through mode, and opens the same menu, so
               she can always be configured, moved, hidden, or closed.
      pointer  the line and outline drawn when she points. It never
               accepts mouse input, so it cannot get in the way of
               whatever she is pointing at.

    It uses tkinter, which comes with Python, so it needs nothing
    installed and no graphics card.
    """

    id = "tk-placeholder"
    name = "Placeholder figure"
    cost = 0
    needs_gpu = False
    appearances = tuple(APPEARANCES)

    @classmethod
    def available(cls):
        try:
            import tkinter  # noqa: F401
        except Exception:
            return "tkinter is not available in this Python."

        return None

    def read_layout(self):
        # Must happen before any window exists, or Windows hands this
        # process coordinates scaled for the primary monitor only.
        enable_dpi_awareness()

        try:
            return read_windows_layout()
        except GeometryError:
            return single_display_layout()

    # -- windows ---------------------------------------------------------------

    def _window(self, tk, root, interactive: bool):
        window = tk.Toplevel(root)
        window.overrideredirect(True)
        window.configure(bg=CLEAR)
        window.attributes("-transparentcolor", CLEAR)
        window.attributes("-topmost", True)
        canvas = tk.Canvas(window, bg=CLEAR, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        window.update_idletasks()
        self._style(window, click_through=not interactive)
        window.withdraw()

        return window, canvas

    def _style(self, window, click_through: bool) -> None:
        if os.name != "nt":
            return

        try:
            import ctypes

            user32 = ctypes.windll.user32
            handle = user32.GetParent(window.winfo_id()) or window.winfo_id()
            style = user32.GetWindowLongW(handle, GWL_EXSTYLE)
            style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE

            if click_through:
                style |= WS_EX_TRANSPARENT
            else:
                style &= ~WS_EX_TRANSPARENT

            user32.SetWindowLongW(handle, GWL_EXSTYLE, style)
        except Exception:
            pass

    # -- the main loop -----------------------------------------------------------

    def run(self, session) -> None:
        import tkinter as tk

        self._tk = tk
        self._session = session
        self._model = session.model
        self._root = tk.Tk()
        self._root.withdraw()

        self._body, self._body_canvas = self._window(tk, self._root, True)
        self._pointer, self._pointer_canvas = self._window(tk, self._root, False)
        self._handle, self._handle_canvas = self._window(tk, self._root, True)

        self._click_through = False
        self._drag = None
        self._drawn = None
        self._last_tick = time.perf_counter()
        self._last_layout_check = 0.0
        self._started = time.perf_counter()

        self._body_canvas.bind("<ButtonPress-1>", self._drag_start)
        self._body_canvas.bind("<B1-Motion>", self._drag_move)
        self._body_canvas.bind("<ButtonRelease-1>", self._drag_end)
        self._body_canvas.bind("<Button-3>", self._open_menu)
        self._body_canvas.bind("<MouseWheel>", self._wheel)
        self._handle_canvas.bind("<Button-1>", self._open_menu)
        self._handle_canvas.bind("<Button-3>", self._open_menu)

        self._prepare()
        session.on_configure = self._configured
        self._configured(self._model.config)

        self._root.after(0, self._frame)
        self._root.mainloop()

    def _prepare(self) -> None:
        """
        For a renderer built on this one: called once its windows
        exist, before the first frame.
        """

    def _configured(self, config) -> None:
        for window in (self._body, self._pointer, self._handle):
            window.attributes("-topmost", config.always_on_top)

        if config.click_through != self._click_through:
            self._click_through = config.click_through
            self._style(self._body, click_through=config.click_through)

        self._drawn = None

    def _frame(self) -> None:
        session = self._session

        try:
            if not session.pump():
                self._root.destroy()
                return

            now = time.perf_counter()
            self._model.tick(now - self._last_tick)
            self._last_tick = now

            if now - self._last_layout_check > LAYOUT_CHECK_SECONDS:
                self._last_layout_check = now

                try:
                    session.set_layout(read_windows_layout())
                except GeometryError:
                    pass

            self._draw(now - self._started)
        except self._tk.TclError:
            # A window was destroyed underneath us; stop cleanly.
            session.running = False
            return

        self._root.after(max(int(session.frame_interval() * 1000), 5), self._frame)

    # -- what the user does to her ---------------------------------------------

    def _drag_start(self, event) -> None:
        rect = self._model.rect
        self._drag = (event.x_root - rect.left, event.y_root - rect.top)

    def _drag_move(self, event) -> None:
        if self._drag is not None:
            self._model.drag_to(
                event.x_root - self._drag[0], event.y_root - self._drag[1]
            )
            self._draw(time.perf_counter() - self._started)

    def _drag_end(self, event) -> None:
        if self._drag is None:
            return

        self._drag = None
        rect = self._model.rect
        self._session.emit(
            c.event(
                c.USER_MOVED,
                x=rect.left,
                y=rect.top,
                display=self._model.display_id,
            )
        )

    def _wheel(self, event) -> None:
        step = WHEEL_STEP_PERCENT if event.delta > 0 else -WHEEL_STEP_PERCENT
        self._resize_by(step)

    def _resize_by(self, step) -> None:
        size = self._model.user_resize(self._model.size_percent + step)
        self._session.emit(c.event(c.USER_RESIZED, percent=size))

    def _setting(self, key, value) -> None:
        self._session.emit(c.event(c.USER_SETTING, key=key, value=value))

    def _open_menu(self, event) -> None:
        tk = self._tk
        model = self._model
        menu = tk.Menu(self._root, tearoff=0)

        size = tk.Menu(menu, tearoff=0)
        size.add_command(label="Larger", command=lambda: self._resize_by(5))
        size.add_command(label="Smaller", command=lambda: self._resize_by(-5))
        size.add_command(
            label="Preferred size",
            command=lambda: self._resize_by(
                model.config.limits_for(model.display_id).preferred
                - model.size_percent
            ),
        )
        menu.add_cascade(label="Size", menu=size)

        looks = tk.Menu(menu, tearoff=0)

        for appearance in APPEARANCES.values():
            looks.add_command(
                label=("• " if appearance.id == model.appearance else "   ")
                + appearance.name,
                command=lambda chosen=appearance.id: self._choose_appearance(chosen),
            )

        menu.add_cascade(label="Appearance", menu=looks)
        menu.add_separator()
        menu.add_command(
            label=(
                "Turn click-through off"
                if self._click_through
                else "Turn click-through on"
            ),
            command=lambda: self._setting("click_through", not self._click_through),
        )
        menu.add_command(
            label=(
                "Stop staying on top"
                if model.config.always_on_top
                else "Stay on top"
            ),
            command=lambda: self._setting(
                "always_on_top", not model.config.always_on_top
            ),
        )
        menu.add_command(
            label="Return to resting place",
            command=lambda: self._session.put(c.command(c.RETURN_TO_REST)),
        )
        menu.add_separator()
        menu.add_command(label="Hide", command=lambda: self._setting("visible", False))
        menu.add_command(
            label="Close the avatar",
            command=lambda: self._session.emit(c.event(c.EXIT_REQUESTED)),
        )

        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _choose_appearance(self, appearance) -> None:
        self._session.put(c.command(c.SET_APPEARANCE, appearance=appearance))
        self._setting("appearance", appearance)

    # -- drawing -----------------------------------------------------------------

    def _draw(self, seconds: float) -> None:
        frame = self._model.frame()

        if not frame["visible"]:
            if self._drawn != "hidden":
                for window in (self._body, self._pointer, self._handle):
                    window.withdraw()
                self._drawn = "hidden"
            return

        if self._drawn == "hidden" or self._drawn is None:
            self._body.deiconify()
            self._handle.deiconify()

        rect = frame["rect"]
        width = max(int(round(rect.width)), 8)
        height = max(int(round(rect.height)), 8)
        left, top = int(round(rect.left)), int(round(rect.top))
        look = frame["appearance"]

        self._body.geometry(f"{width}x{height}{left:+d}{top:+d}")
        self._body.attributes("-alpha", look.opacity)
        self._figure(self._body_canvas, width, height, frame, seconds)

        # The handle sits just outside her top-right corner, moved
        # inside if that would put it off the display.
        display = self._model.layout.display_for_rect(rect)
        handle_left = min(left + width - HANDLE_SIZE // 2, int(display.bounds.right) - HANDLE_SIZE)
        handle_top = max(top - HANDLE_SIZE // 3, int(display.bounds.top))
        self._handle.geometry(
            f"{HANDLE_SIZE}x{HANDLE_SIZE}{handle_left:+d}{handle_top:+d}"
        )
        self._draw_handle(look)

        self._draw_pointer(frame, look)
        self._drawn = "shown"

    def _draw_handle(self, look) -> None:
        canvas = self._handle_canvas
        canvas.delete("all")
        size = HANDLE_SIZE
        canvas.create_oval(
            2, 2, size - 2, size - 2,
            fill=look.clothing, outline=look.outline, width=2,
        )

        for row in (0.36, 0.5, 0.64):
            canvas.create_line(
                size * 0.3, size * row, size * 0.7, size * row,
                fill=look.accent, width=2,
            )

    def _draw_pointer(self, frame, look) -> None:
        pointer = frame["pointer"]

        if pointer is None:
            if self._pointer.state() != "withdrawn":
                self._pointer.withdraw()
            return

        bounds = self._model.layout.virtual_bounds
        self._pointer.geometry(
            f"{int(bounds.width)}x{int(bounds.height)}"
            f"{int(bounds.left):+d}{int(bounds.top):+d}"
        )

        if self._pointer.state() == "withdrawn":
            self._pointer.deiconify()
            self._style(self._pointer, click_through=True)

        canvas = self._pointer_canvas
        canvas.delete("all")
        ox, oy = bounds.left, bounds.top
        start_x, start_y = pointer["from"]
        end_x, end_y = pointer["to"]
        amount = pointer["amount"]
        tip_x = start_x + (end_x - start_x) * amount
        tip_y = start_y + (end_y - start_y) * amount

        canvas.create_line(
            start_x - ox, start_y - oy, tip_x - ox, tip_y - oy,
            fill=look.outline, width=7, capstyle="round",
        )
        canvas.create_line(
            start_x - ox, start_y - oy, tip_x - ox, tip_y - oy,
            fill=look.clothing, width=3, capstyle="round",
            arrow="last", arrowshape=(18, 22, 8),
        )

        if amount > 0.6:
            target = pointer["target"]
            pad = 6
            canvas.create_rectangle(
                target.left - ox - pad, target.top - oy - pad,
                target.right - ox + pad, target.bottom - oy + pad,
                outline=look.clothing, width=3, dash=(8, 5),
            )

    def _figure(self, canvas, width, height, frame, seconds) -> None:
        canvas.delete("all")
        look = frame["appearance"]
        line = max(height // 90, 1)
        bob = frame["breath"] * height * 0.006
        center = width / 2

        head_radius = height * 0.15
        head_y = height * 0.19 + bob
        shoulder_y = height * 0.40

        # Body: a rounded torso narrowing to the feet.
        canvas.create_polygon(
            center - width * 0.40, shoulder_y + height * 0.06,
            center - width * 0.30, shoulder_y - height * 0.02,
            center + width * 0.30, shoulder_y - height * 0.02,
            center + width * 0.40, shoulder_y + height * 0.06,
            center + width * 0.30, height - line,
            center - width * 0.30, height - line,
            fill=look.clothing, outline=look.outline, width=line, smooth=True,
        )

        # Arm: raised and swinging when waving, turned toward the
        # target when pointing, resting otherwise.
        hand = self._hand(frame, center, shoulder_y, height, seconds)

        if hand is not None:
            canvas.create_line(
                center + width * 0.22, shoulder_y + height * 0.03, hand[0], hand[1],
                fill=look.skin, width=max(int(height * 0.035), 3), capstyle="round",
            )

        # Head, with hair behind it for appearances that have any.
        if look.hair != look.skin:
            canvas.create_oval(
                center - head_radius * 1.08, head_y - head_radius * 1.14,
                center + head_radius * 1.08, head_y + head_radius * 0.70,
                fill=look.hair, outline="",
            )

        canvas.create_oval(
            center - head_radius, head_y - head_radius,
            center + head_radius, head_y + head_radius,
            fill=look.skin, outline=look.outline, width=line,
        )

        self._face(canvas, frame, center, head_y, head_radius, line, seconds)

        if look.glow:
            canvas.create_oval(
                center - head_radius * 1.25, head_y - head_radius * 1.25,
                center + head_radius * 1.25, head_y + head_radius * 1.25,
                outline=look.accent, width=line,
            )

        if look.scanlines:
            # Lines in the clear colour, so the desktop shows through.
            offset = int(seconds * 24) % 6

            for y in range(offset, height, 6):
                canvas.create_line(0, y, width, y, fill=CLEAR, width=2)

    def _hand(self, frame, center, shoulder_y, height, seconds):
        reach = height * 0.24

        if frame["wave"] is not None:
            angle = math.radians(-65 + 22 * math.sin(frame["wave"] * math.pi * 6))

            return (
                center + self._model.rect.width * 0.22 + reach * math.cos(angle),
                shoulder_y + reach * math.sin(angle),
            )

        pointer = frame["pointer"]

        if pointer is None:
            return None

        rect = frame["rect"]
        dx = pointer["to"][0] - pointer["from"][0]
        dy = pointer["to"][1] - pointer["from"][1]
        length = math.hypot(dx, dy) or 1.0
        reach *= pointer["amount"]

        return (
            (pointer["from"][0] - rect.left) + dx / length * reach,
            (pointer["from"][1] - rect.top) + dy / length * reach,
        )

    def _face(self, canvas, frame, center, head_y, radius, line, seconds) -> None:
        look = frame["appearance"]
        expression = frame["expression"]
        eye_y = head_y - radius * 0.12
        eye_gap = radius * 0.42
        eye = radius * (0.20 if expression == "surprised" else 0.15)

        # The pupils turn toward what she is looking at.
        shift_x = shift_y = 0.0

        if frame["gaze"] is not None:
            rect = frame["rect"]
            dx = frame["gaze"][0] - (rect.left + center)
            dy = frame["gaze"][1] - (rect.top + head_y)
            length = math.hypot(dx, dy) or 1.0
            shift_x, shift_y = dx / length * eye * 0.5, dy / length * eye * 0.5

        for side in (-1, 1):
            x = center + side * eye_gap
            canvas.create_oval(
                x - eye, eye_y - eye, x + eye, eye_y + eye,
                fill=look.accent, outline=look.outline, width=line,
            )
            canvas.create_oval(
                x - eye * 0.5 + shift_x, eye_y - eye * 0.5 + shift_y,
                x + eye * 0.5 + shift_x, eye_y + eye * 0.5 + shift_y,
                fill=look.outline, outline="",
            )

            if expression in ("thinking", "concerned"):
                tilt = radius * 0.10 * (side if expression == "concerned" else -side)
                canvas.create_line(
                    x - eye, eye_y - eye * 1.7 - tilt,
                    x + eye, eye_y - eye * 1.7 + tilt,
                    fill=look.outline, width=line * 2,
                )

        mouth_y = head_y + radius * 0.48
        mouth = radius * 0.34

        if frame["speaking"]:
            opening = radius * (
                0.10 + 0.22 * frame["speech_level"] * abs(math.sin(seconds * 11))
            )
            canvas.create_oval(
                center - mouth * 0.7, mouth_y - opening,
                center + mouth * 0.7, mouth_y + opening,
                fill=look.outline, outline="",
            )
        elif expression == "surprised":
            canvas.create_oval(
                center - mouth * 0.4, mouth_y - mouth * 0.4,
                center + mouth * 0.4, mouth_y + mouth * 0.4,
                fill=look.outline, outline="",
            )
        elif expression == "happy":
            canvas.create_arc(
                center - mouth, mouth_y - mouth, center + mouth, mouth_y + mouth * 0.6,
                start=200, extent=140, style="arc", outline=look.outline, width=line * 2,
            )
        elif expression == "concerned":
            canvas.create_arc(
                center - mouth, mouth_y, center + mouth, mouth_y + mouth * 1.4,
                start=20, extent=140, style="arc", outline=look.outline, width=line * 2,
            )
        else:
            canvas.create_line(
                center - mouth * 0.7, mouth_y, center + mouth * 0.7, mouth_y,
                fill=look.outline, width=line * 2,
            )
