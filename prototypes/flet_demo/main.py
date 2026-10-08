"""A small Flet prototype for trying out interface ideas.

It is separate from Freya: nothing here talks to her, and nothing in
Freya imports it. Run it with:

    flet run prototypes/flet_demo/main.py

It shows a custom theme, navigation, a form with validation, and a
layout that changes between a desktop-sized and a phone-sized window.
"""

import flet as ft


# Below this width the layout switches to its phone arrangement.
PHONE_WIDTH = 720

# The one colour the whole theme is generated from.
SEED_COLOR = "#7C9CFF"

SECTIONS = [
    ("Chat", ft.Icons.CHAT_BUBBLE_OUTLINE, ft.Icons.CHAT_BUBBLE),
    ("Images", ft.Icons.IMAGE_OUTLINED, ft.Icons.IMAGE),
    ("Settings", ft.Icons.SETTINGS_OUTLINED, ft.Icons.SETTINGS),
]

SAMPLE_IMAGES = [
    "A lighthouse on a rocky coast at sunset",
    "A small sailboat on a calm lake",
    "A red fox sitting in fresh snow",
    "A large black dog in a grassy field",
    "A city skyline in the rain",
    "A mountain cabin under the northern lights",
]

VOICES = [
    ("heart", "Heart"),
    ("bella", "Bella"),
    ("nicole", "Nicole"),
    ("sky", "Sky"),
]


def make_theme() -> ft.Theme:
    return ft.Theme(
        color_scheme_seed=SEED_COLOR,
        font_family="Segoe UI",
        use_material3=True,
        visual_density=ft.VisualDensity.COMFORTABLE,
    )


def bubble(text: str, mine: bool) -> ft.Row:
    return ft.Row(
        alignment=(
            ft.MainAxisAlignment.END
            if mine
            else ft.MainAxisAlignment.START
        ),
        controls=[
            ft.Container(
                content=ft.Text(text, selectable=True),
                padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                border_radius=ft.BorderRadius.all(14),
                bgcolor=(
                    ft.Colors.PRIMARY_CONTAINER
                    if mine
                    else ft.Colors.SURFACE_CONTAINER_HIGHEST
                ),
                width=None,
            )
        ],
    )


def chat_view(page: ft.Page) -> ft.Control:
    messages = ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=10,
        controls=[
            bubble("Hello. This is a layout prototype.", mine=False),
            bubble("Type below to see how messages stack.", mine=False),
        ],
    )

    box = ft.TextField(
        hint_text="Message",
        expand=True,
    )

    def send(_event=None):
        text = (box.value or "").strip()

        if not text:
            return

        messages.controls.append(bubble(text, mine=True))
        messages.controls.append(
            bubble(
                "Nothing is connected yet, so that went nowhere.",
                mine=False,
            )
        )
        box.value = ""
        page.update()

    box.on_submit = send

    return ft.Column(
        expand=True,
        spacing=12,
        controls=[
            messages,
            ft.Row(
                controls=[
                    box,
                    ft.IconButton(
                        icon=ft.Icons.SEND,
                        tooltip="Send",
                        on_click=send,
                    ),
                ],
            ),
        ],
    )


def images_view(page: ft.Page) -> ft.Control:
    cards = [
        ft.Card(
            # One per row on a phone, two on a tablet, three on a desktop.
            col={"xs": 12, "sm": 6, "lg": 4},
            content=ft.Column(
                spacing=0,
                controls=[
                    ft.Container(
                        height=140,
                        bgcolor=ft.Colors.PRIMARY_CONTAINER,
                        border_radius=ft.BorderRadius.only(
                            top_left=12,
                            top_right=12,
                        ),
                        alignment=ft.Alignment(0, 0),
                        content=ft.Icon(
                            ft.Icons.IMAGE,
                            size=40,
                            color=ft.Colors.ON_PRIMARY_CONTAINER,
                        ),
                    ),
                    ft.Container(
                        padding=ft.Padding.all(12),
                        content=ft.Text(caption),
                    ),
                ],
            ),
        )
        for caption in SAMPLE_IMAGES
    ]

    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        controls=[
            ft.Text(
                "Placeholders standing in for generated images.",
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.ResponsiveRow(controls=cards, spacing=12, run_spacing=12),
        ],
    )


def settings_view(page: ft.Page) -> ft.Control:
    # Fields sit side by side on a wide window and stack on a narrow one.
    half = {"xs": 12, "md": 6}

    name = ft.TextField(
        label="Name she answers to",
        value="Freya",
        col=half,
    )

    voice = ft.Dropdown(
        label="Voice",
        value=VOICES[0][0],
        options=[
            ft.DropdownOption(key=key, text=label)
            for key, label in VOICES
        ],
        col=half,
    )

    listen = ft.Switch(
        label="Listen for her name",
        value=True,
        col=half,
    )

    speed_label = ft.Text("Speaking speed: 1.0x")

    def speed_changed(event):
        speed_label.value = f"Speaking speed: {event.control.value:.1f}x"
        page.update()

    speed = ft.Slider(
        min=0.5,
        max=1.5,
        divisions=10,
        value=1.0,
        on_change=speed_changed,
    )

    def save(_event):
        entered = (name.value or "").strip()

        if not entered:
            name.error = "Enter at least one name."
            page.update()
            return

        if not entered.replace(" ", "").isalpha():
            name.error = "Use letters only."
            page.update()
            return

        name.error = None
        summary = (
            f"Saved: {entered}, voice {voice.value}, "
            f"{'listening' if listen.value else 'muted'}, "
            f"{speed.value:.1f}x."
        )
        saved.value = summary
        page.show_dialog(ft.SnackBar(content=ft.Text(summary)))
        page.update()

    saved = ft.Text("", color=ft.Colors.PRIMARY)

    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=18,
        controls=[
            ft.Text(
                "A sample form. Nothing here is saved anywhere.",
                color=ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.ResponsiveRow(
                controls=[name, voice, listen],
                spacing=16,
                run_spacing=16,
            ),
            ft.Column(
                spacing=0,
                controls=[speed_label, speed],
            ),
            ft.Row(
                controls=[
                    ft.FilledButton(
                        content="Save",
                        icon=ft.Icons.CHECK,
                        on_click=save,
                    ),
                ],
            ),
            saved,
        ],
    )


VIEWS = [chat_view, images_view, settings_view]


def main(page: ft.Page):
    page.title = "Interface prototype"
    page.theme = make_theme()
    page.dark_theme = make_theme()
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0

    page.window.width = 1100
    page.window.height = 760
    page.window.min_width = 360
    page.window.min_height = 520

    selected = {"index": 0}

    # Each section is built once and kept, so what was typed survives
    # switching sections or resizing.
    built = {}

    content = ft.Container(expand=True, padding=ft.Padding.all(20))

    def show(index: int):
        selected["index"] = index

        if index not in built:
            built[index] = VIEWS[index](page)

        content.content = built[index]
        rail.selected_index = index
        bar.selected_index = index
        page.update()

    def section_chosen(event):
        show(event.control.selected_index)

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=84,
        destinations=[
            ft.NavigationRailDestination(
                icon=icon,
                selected_icon=selected_icon,
                label=label,
            )
            for label, icon, selected_icon in SECTIONS
        ],
        on_change=section_chosen,
    )

    bar = ft.NavigationBar(
        selected_index=0,
        destinations=[
            ft.NavigationBarDestination(
                icon=icon,
                selected_icon=selected_icon,
                label=label,
            )
            for label, icon, selected_icon in SECTIONS
        ],
        on_change=section_chosen,
    )

    divider = ft.VerticalDivider(width=1)

    def toggle_theme(_event):
        dark = page.theme_mode == ft.ThemeMode.DARK
        page.theme_mode = ft.ThemeMode.LIGHT if dark else ft.ThemeMode.DARK
        theme_button.icon = ft.Icons.DARK_MODE if dark else ft.Icons.LIGHT_MODE
        page.update()

    theme_button = ft.IconButton(
        icon=ft.Icons.LIGHT_MODE,
        tooltip="Switch between dark and light",
        on_click=toggle_theme,
    )

    page.appbar = ft.AppBar(
        title=ft.Text("Interface prototype"),
        bgcolor=ft.Colors.SURFACE_CONTAINER,
        actions=[theme_button],
    )

    def arrange(_event=None):
        """
        A side rail on a wide window; a bottom bar on a narrow one.
        """
        width = getattr(_event, "width", None) or page.width
        narrow = (width or PHONE_WIDTH) < PHONE_WIDTH

        rail.visible = not narrow
        divider.visible = not narrow
        page.navigation_bar = bar if narrow else None
        content.padding = ft.Padding.all(12 if narrow else 20)
        page.update()

    page.on_resize = arrange

    page.add(
        ft.Row(
            expand=True,
            spacing=0,
            controls=[rail, divider, content],
        )
    )

    show(0)
    arrange()


if __name__ == "__main__":
    ft.run(main)
