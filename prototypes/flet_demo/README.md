# Flet interface prototype

A small stand-alone Flet app for trying out interface ideas. It is not part of
Freya: nothing here talks to her, and nothing in `src/freya` imports it.

It demonstrates:

- a custom theme generated from one seed colour, with a dark/light switch;
- navigation between three sections (Chat, Images, Settings);
- a form with validation;
- a layout that adapts: a side rail and multi-column content on a wide
  window, a bottom bar and single column on a phone-sized one.

## Running it

From the repository root, with the project's virtual environment:

```
.venv\Scripts\flet run prototypes\flet_demo\main.py
```

The first desktop run downloads Flet's desktop client (from the Flet project's
releases) into your user profile. To run it in a browser instead, with no
download:

```
.venv\Scripts\flet run --web prototypes\flet_demo\main.py
```

Resize the window narrower than 720 pixels to see the phone layout.

## Packaging later

Running the prototype needs nothing beyond the `flet` packages already in the
project. Building installable apps needs more, none of which is installed yet:

| Target  | Needs |
|---------|-------|
| Windows | Flutter SDK (fetched by `flet build`), Visual Studio with "Desktop development with C++" |
| Android | Android SDK (Android Studio) and JDK 17 |
| Linux   | A Linux machine or WSL distribution with clang, CMake, Ninja, and GTK 3 development files |
| macOS   | A Mac with Xcode and CocoaPods |
| iOS     | A Mac with Xcode and CocoaPods, plus an Apple Developer account |
