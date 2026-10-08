"""
Freya's spatial avatar: a character that appears on the desktop, moves,
resizes, and points at things.

The avatar is a client-side capability. Nothing in Freya Core depends
on it, and it depends on no particular rendering engine: everything a
renderer needs arrives as plain commands (commands.py) and everything
it reports comes back as plain events.

Layout of the package:

  geometry    displays, rectangles, and coordinate conversion
  config      size limits, boundaries, and per-user settings
  targets     where something is on screen, and whether that is still true
  commands    the renderer-independent command and event vocabulary
  animation   cancellable, prioritised animations
  placement   where to stand so as not to cover what is being pointed at
  model       the avatar's state, advanced one frame at a time
  appearance  appearance profiles sharing one character
  speech      speech and facial-animation interfaces
  renderers   drawing backends (a placeholder and a null one)
  overlay     the separate process a renderer runs in
  host        starts, feeds, and survives the overlay process
  service     the capabilities, permissions, and window requests
"""

# Version of the command and event vocabulary spoken between the host
# and a renderer. A renderer that reports a different major version is
# not sent commands.
PROTOCOL_VERSION = 1
