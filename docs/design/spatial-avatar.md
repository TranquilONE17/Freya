# Spatial avatar and desktop interaction: Phase 1

**Status: Phase 1 implemented (`src/freya/spatial_avatar/`). Phases 2 to 5 are
plans only.** This document says what was built, what is a stub, and what is
proposed. It adopts no architecture decision and assigns no requirement IDs.

Baseline references are to *Freya Foundation v1.1*. NEW-x labels are pending
amendments, not adopted requirements.

## 1. Assessment of the repository before this work

| Area | What was found | Consequence |
|---|---|---|
| Avatar, rendering, animation, screen capture | Nothing existed. | Built new, as a package of its own. |
| Where an avatar belongs | The baseline lists Avatar among the clients that sit outside Core behind the Client Gateway (GUI-001 to GUI-005) and says unrestricted desktop control is not the default (PHY-003). | The avatar is a client-side capability. Core does not import it. |
| Capability and provider registries, broker | Present and used for system tools, the model, and images. | The avatar registers a provider and three capabilities and is reached only through the broker. |
| Event handling | `EventBus` announces replies; nothing announced speech starting or ending. | A small listener hook was added to the voice. |
| GUI | A browser app window. It cannot be transparent, stay on top, or pass clicks through. | The overlay is a separate program. The window gained an Avatar tab for settings. |
| Speech | Kokoro in-process, plus helper-process engines. | The avatar listens for speech phases and knows nothing about engines. |
| Identity | One fixed `local-owner`; no sessions or client scopes. | Settings are stored per user, but there is one user today. Per-client permissions wait for the authenticated gateway. |
| Resource management | A GPU hand-off between Ollama and ComfyUI; no general admission control. | The placeholder uses no GPU. Renderers declare their cost so one can be chosen to fit. |

Risks noted: there is no authenticated session to scope avatar permissions to a
client; screen awareness (Phase 2) touches the most sensitive data Freya could
see, so it must not be started before its permissions and approval path exist.

## 2. Architecture

```
                       Freya (one process)                          separate process
 ┌──────────────────────────────────────────────────────┐      ┌───────────────────────┐
 │ window (Avatar tab) ──► gateway ──► AvatarService    │      │ overlay               │
 │                                       │  ▲           │      │  Session              │
 │                          broker.invoke│  │events     │      │   └ AvatarModel       │
 │   policy ─ audit ─ CapabilityBroker ◄─┘  │           │      │       └ Animator      │
 │        avatar.display                    │           │ JSON │  Renderer             │
 │        screen.geometry.read          AvatarHost ◄────┼──────┤   tk-placeholder      │
 │        avatar.point                      │  commands │lines │   null                │
 │                                          └───────────┼─────►│   (future: 3D engine) │
 │ voice ── speech phases ──► AvatarService             │      └───────────────────────┘
 │ TargetRegistry ◄ MockTargetProvider, UserRegionProvider                             │
 └──────────────────────────────────────────────────────┘
```

Dependencies run one way: `service` and `host` (in Freya) know the command
vocabulary; the overlay knows the vocabulary, the model, and a renderer; a renderer
knows how to draw. Core imports none of it. The overlay imports none of Core, opens
none of Freya's data, and cannot invoke a capability. A test enforces each of these.

| Module | Role | Runs in |
|---|---|---|
| `geometry` | Displays, rectangles, conversion between coordinate systems | both |
| `config` | Size limits, boundaries, restricted regions; per-user store | both |
| `targets` | `SpatialTarget`, target providers, revalidation | Freya |
| `commands` | The versioned command and event vocabulary | both |
| `animation` | Cancellable, prioritised animations | overlay |
| `placement` | Where to stand so as not to cover the target | overlay |
| `model` | The avatar's whole behaviour, with no drawing | overlay |
| `appearance` | Appearance profiles sharing one character | both |
| `speech` | Speech listener; lip-sync and facial interfaces (stubs) | Freya |
| `renderers/` | Drawing backends | overlay |
| `overlay` | The overlay program's entry point | overlay |
| `host` | Starts, feeds, and survives the overlay | Freya |
| `service` | Capabilities, permissions, window requests | Freya |

**Replacing a renderer.** A renderer draws what `AvatarModel.frame()` describes and
reports what the user does. It decides nothing. A 3D engine would be a new entry in
`renderers.RENDERERS`, or a separate program speaking the same JSON commands and
events; nothing else changes. Behaviour stays identical because it lives in the
model. `choose_renderer` picks by availability, GPU, and cost, and falls back.

**Versioning.** Every command and event carries `v` (`PROTOCOL_VERSION`, now 1). A
renderer announcing a different version is not used. Unknown fields are ignored.

## 3. What Phase 1 implements

- **Overlay** (Windows): a transparent, borderless figure that stays above other
  windows and never takes keyboard focus. Drag to move, wheel to resize, right-click
  for a menu. Runs as its own process; Freya survives it crashing and it exits when
  Freya does.
- **Click-through**: the mouse passes through her. A small round handle beside her
  always accepts clicks and opens the same menu, and the window's Avatar tab still
  works, so she can always be configured, moved, hidden, or closed.
- **Scaling**: minimum, maximum, and preferred size as a percentage of a display's
  usable height (defaults 8, 65, 25); per-display limits; automatic or manual size;
  smooth transitions. A size outside the range is clamped, and she never passes
  through a forbidden size on the way.
- **Boundaries**: an allowed area per display and restricted regions she stays out
  of, held on every frame of a move and while dragged. If a display is unplugged
  she returns to one that exists.
- **Multiple monitors and DPI**: the overlay declares per-monitor DPI awareness, so
  coordinates are true pixels. Layout changes are detected every two seconds.
- **Commands**: move to, look at, point at, wave, idle, set expression, resize,
  set appearance, return to rest; each cancellable, with priorities and
  interruption.
- **Pointing**: she walks beside the target, raises an arm, looks at it, and a line
  with an outline marks it. She avoids covering it whenever a clear position exists
  inside her boundary, and says so when none does.
- **Targets**: a normalized `SpatialTarget` (identifier, display, coordinate
  system, rectangle, confidence, source, timestamp, validity). Phase 1 providers:
  made-up demonstration targets, and regions the user picks on a map of the display.
  Targets are revalidated before every use and invalidated when the layout changes.
- **Appearances**: lightweight, realistic, and holographic placeholders sharing one
  character, switchable while she is on screen.
- **Speech**: she is told when speech starts, completes, or is interrupted, and
  opens and closes her mouth.
- **Settings**: saved per user in `data/avatar_settings.json`, changeable while
  running from the Avatar tab or the overlay's menu. Where the user drags her
  becomes where she rests.
- **Resources**: full frame rate only while moving or speaking, a slow rate when
  idle, and no drawing when hidden.

### Stubs and proposals, not implementations

- `speech.Viseme`, `FaceFrame`, `FacialAnimationBackend`: interfaces only.
- `speech_progress(level)`: accepted, but nothing sends a level yet.
- `quality` setting and `Appearance` material hints beyond colour, opacity,
  scanlines, and glow: stored and passed on; the placeholder ignores the rest.
- The six future permissions in section 4: names only.
- "Realistic" is a coloured placeholder, not a photorealistic character.
- GPU utilisation reporting: not implemented (the placeholder uses none).

## 3a. Avatar library and preview (added after Phase 1)

The first two stages of an avatar creation system. They let the owner bring in
VRM avatar models and look at them; they do not yet put a model on the desktop.

**Implemented**

- **Reading VRM files** (`vrm.py`): a VRM file is a glTF binary file with an avatar
  description. Freya reads the description only: name, authors, the terms of use,
  expressions and mouth shapes, skeleton, a thumbnail, and size. Both VRM 0.x and
  1.0 are read, and their differently-named terms are put into one plain form.
- **Library** (`library.py`): the `.vrm` files directly inside
  `data/avatar_models/`, which the owner fills. Freya never changes, moves, or
  deletes them. A model is known by the SHA-256 of its contents. Files that are not
  usable are listed with the reason.
- **Saved avatars**: a named choice of one model, one of which can be marked as
  Freya's. Kept in `data/avatar_library.json`.
- **Terms of use**: every model's own terms are shown in plain words. A model whose
  terms let only its author, or only licensed people, use it, or that states no
  terms, can be saved as an avatar only with the owner's confirmation that they
  may; what was confirmed, and when, is kept with the avatar.
- **3D preview** (`gateway/static/avatar-view.js`): the model is drawn in the Avatar
  tab, can be turned and zoomed, and its expressions tried. Drawing stops while the
  tab is not showing.
- A fourth capability, `avatar.library`, with its own policy seed
  `alpha-avatar-library`. Looking at the folder and changing saved avatars go
  through the broker and are audited.

**Downloaded files are untrusted.** The format contains no code and nothing in a
file is executed. Sizes and offsets are checked before reading; text is cut to
length and stripped of control characters, and is only ever placed on the page as
text; a thumbnail is served only if its bytes really begin as the PNG or JPEG the
file claims; only models found by scanning the folder can be fetched, by their
hash; links and files outside the folder are ignored.

**Third-party code.** The preview uses three.js 0.186.1 and @pixiv/three-vrm 3.5.5,
both MIT-licensed, copied unmodified into `gateway/static/vendor/` with their
licences. Each package was checked against the npm registry's published SHA-512,
and the SHA-256 of every copied file is recorded in `vendor/README.txt` and checked
by a test. They run only in the window's page.

**Content security policy.** Two narrow additions were needed: the page's import map
(its one inline script, which only says where the page's own library files are) is
allowed by the hash of its exact text; and `blob:` is allowed for images and
fetches, because a model's textures are unpacked inside the page. Inline scripts in
general, `eval`, and loading from anywhere else remain refused.

### Finding models and making them ready

- **Search** (`sources.py`, capability `avatar.search`): pressing Search in the
  Avatar tab looks in the owner's Downloads folder (or the folders named in
  `FREYA_AVATAR_SEARCH`, separated by `;`) and two levels below it. Each 3D file is
  listed as *ready* (a VRM), *needs converting* (`.blend`, `.fbx`, `.glb`, `.gltf`,
  or a `.zip`/`.7z`/`.rar` containing one), or *cannot be used* (`.stl`, `.obj`
  and other surface-only formats, with the reason). Only names and sizes are read,
  and the list of names inside an archive; no model is opened and nothing is
  unpacked.
- **Make ready** (`converter.py`, capability `avatar.prepare`): a VRM is copied into
  the avatar folder. Anything else is unpacked if needed, the most promising file is
  chosen (one named as rigged before one named as unrigged or posed), and Blender
  inspects it (`blender/inspect_model.py`) and reports its skeleton, size, and face
  shapes. From that report Freya decides what is needed and says so in plain words,
  then converts it (`blender/convert_model.py`): a production animation rig
  (Auto-Rig Pro) is replaced by a plain humanoid skeleton and every part re-attached
  to it; a model not made in metres is resized; hair pieces are joined; clear eye
  coatings that a simple renderer would draw as white are removed; materials are
  reduced to what an avatar file can hold; and the standard expressions and mouth
  shapes are built from the model's face shapes. Every one of the 52 standard face
  shapes the model has is also kept as a named expression of its own, for finer
  animation later; this adds nothing to the file's size.
- **Expression tester**: the preview has a button for every expression the loaded
  model has (the standard ones, then the individual face shapes), a strength
  slider, whole-figure and face views, and a button that rests the face. Several
  expressions can be on together. Saved avatars can be previewed the same way.

**Safeguards.** Only a file the last search found can be made ready, named by an
opaque id, never by a path from the window. The original is never changed; output
goes only to `data/avatar_models/`, under a new name (an existing avatar is never
overwritten), and work files to `data/avatar_work/`, removed afterwards. An archive
is refused if it would write outside its folder, holds links, or unpacks to more
than 8 GB or 5,000 files. Blender runs as a separate program with no window, on
Freya's own two scripts, with `--disable-autoexec` so that scripts embedded in a
model file are not run, and is ended if it runs too long (5 minutes to inspect, 20
to convert) or when Freya exits. One conversion runs at a time, on its own thread;
the window is told how it is going. A converted file is marked with the most
cautious terms (use only by someone its author has licensed, no redistribution),
because Freya does not know the terms it was obtained under: the owner still has to
confirm they may use it before it becomes an avatar.

**Limits.** Blender (with its VRM add-on) must be installed by the owner;
`FREYA_BLENDER` names it if it is not in the usual place. A model with no skeleton
cannot be converted. Only the Auto-Rig Pro route has been tried with a real model;
the route for other skeletons relies on the VRM add-on recognising the bones and is
untested. Hair is attached to the head and does not swing. Opening a model file in
Blender is safer than running it but is not a sandbox: a flaw in Blender's own file
reading would run with the owner's rights. Models bought or downloaded under terms
that forbid passing them on stay under `data/`, which is not in the repository.

**Not implemented**

- **The desktop avatar is still the placeholder figure.** Marking a saved avatar as
  Freya's records the choice; nothing draws it on the desktop yet. That needs a 3D
  renderer for the overlay (stage 4).
- Customising a model (scale, colours, the holographic material, expression
  mapping) is stage 3.
- Creating a character from scratch is stage 5 and may never be built here; VRoid
  Studio already does it and exports VRM.
- Choosing a file from anywhere on the computer through the window. A file has to be
  in a search folder, or be put in the avatar folder by hand.
- **Tried with few real models.** The reader and preview were tested with VRM files
  generated for the purpose, and then with two real ones made on this machine (one
  built in Blender, one converted from a bought model). Toon shading, spring bones,
  and VRM 0.x quirks in models from elsewhere are still unexercised.

## 4. Security and privacy

**The avatar cannot see the screen or send input, because no such code exists.** It
draws, and it reads the layout of the displays so as to draw in the right place. A
test fails if capture, window-enumeration, or input-injection calls appear in the
package.

Each permission is a separate capability, granted or withheld on its own by policy:

| Permission | State | What it allows |
|---|---|---|
| `avatar.display` | Built | Show, hide, move, resize, restyle her |
| `screen.geometry.read` | Built | Positions, sizes, usable areas, scale factors of displays. Nothing shown on them. |
| `avatar.point` | Built | Point at or outline a place. Does not click, type, or change anything. |
| `avatar.library` | Built | Read VRM model files from the avatar folder; keep the owner's saved avatars. Never changes a model file. |
| `avatar.search` | Built | List files in the search folders that are or could become avatars. Reads names and sizes only. |
| `avatar.prepare` | Built | Copy or convert a file the last search found into the avatar folder, using Blender. Never changes the original. |
| `screen.accessibility.read` | Not built | Read what programs report about their windows and controls |
| `screen.capture` | Not built | Capture screen content |
| `screen.analyze` | Not built | Analyse captured content |
| `input.mouse` | Not built | Move or click the mouse |
| `input.keyboard` | Not built | Type or press keys |
| `app.action` | Not built | Carry out an action in a program |

- The three built capabilities are allowed for the local owner by a named policy
  seed, `alpha-avatar`, applied once. Removing a rule withdraws that permission
  alone. The six others have no capability, no rule, and no code; the broker
  refuses them like any unknown capability.
- Every request from the window is a broker invocation: policy check, audit record
  before it runs, outcome after.
- The avatar's capabilities are not offered to the model as tools.
- A target provider declares the permission its kind of looking needs. A provider
  that captured the screen would declare `screen.capture` and is not asked when only
  `avatar.point` is in play, so running the avatar never starts a capture.
- What the user does directly to the overlay (drag, resize, hide, close) is honoured
  without a policy check. Only four settings can be changed that way. The user must
  always be able to move her aside or dismiss her.
- Text that later comes from the screen is untrusted content (CTX-001): it may
  describe a target and is never an instruction. `SpatialTarget.label` is documented
  as such.
- Nothing in Phase 1 sends anything off the computer.

Limits to be aware of: with no authenticated sessions, the "user" is always the
local owner, and per-client scopes do not exist. The overlay process runs as the
same Windows user as Freya; it is isolated against crashes, not against a malicious
renderer.

## 5. Settings

Stored per user. All are changeable while running.

| Setting | Default | Meaning |
|---|---|---|
| `visible` | false | Whether she is shown; restored at the next start |
| `appearance` | lightweight | lightweight, realistic, holographic |
| `size.minimum` / `maximum` / `preferred` | 8 / 65 / 25 | Percent of usable display height |
| `current_size` | none | The size the user last chose by hand |
| `auto_scale` | true | Use the preferred size until the user resizes her |
| `smooth` | true | Animate moves and resizes |
| `always_on_top` | true | Stay above other windows |
| `click_through` | false | Let the mouse pass through her |
| `boundary` | whole usable area | Where she may go, as fractions of the usable area |
| `restricted` | none | Regions she stays out of, per display |
| `displays.<id>.size` / `.boundary` | none | Overrides for one display |
| `rest_display`, `rest_x`, `rest_y` | primary, 0.9, 1.0 | Where she rests |
| `fps_limit` / `idle_fps` | 30 / 5 | Frame rates while moving and while idle |
| `quality` | medium | Passed to the renderer; unused by the placeholder |

Unusable values fall back to defaults; a maximum below the minimum is raised to it;
the preferred size is moved inside the range.

## 6. Resource observations

Measured on the development machine (one 3840 × 2160 display at 300% scale), with
the placeholder renderer: the overlay used about 0.5% of one CPU core while idle and
about 83 MB of memory, with no GPU use. These are single measurements, not a
benchmark.

## 7. Trying it by hand

1. Start Freya and open the **Avatar** tab.
2. Press **Show avatar**. A figure appears at the bottom right.
3. Drag her with the mouse. Roll the wheel over her to resize. Right-click her, or
   click the small round button beside her, for the menu.
4. Move **Size now** in the tab. Then lower **Largest allowed** below her current
   size: she shrinks at once.
5. Change **Appearance** to Holographic and Realistic.
6. Choose a **Demonstration target** and press **Point at it**. She walks beside the
   place, raises an arm, and a dashed outline marks it. She does not stand on it.
7. Drag a small box on the map of the display. She points at that place.
8. Tick **Click-through**. Clicks on her now reach what is underneath. The round
   button still opens her menu; untick it there or in the tab.
9. Move **Left edge** under "Where she may go" to 50%. She moves into the right half
   and cannot be dragged out of it.
10. Ask Freya something with voice on: the avatar's mouth moves while she speaks.
11. End the overlay's process in Task Manager (the `python.exe` whose command line
    contains `freya.spatial_avatar.overlay`). Freya keeps running, the tab says the
    avatar stopped, and **Show avatar** starts her again.
12. Press **Close**, or choose "Close the avatar" from her menu.

## 8. Known limitations

- The figure is a simple drawing. It has not been reviewed for looks.
- Transparency is by colour key, so edges are hard, not blended; translucency in
  holographic mode applies to the whole figure.
- Windows only. Other platforms get the null renderer.
- The pointing line is drawn in a window covering the whole desktop while she
  points. It passes all mouse input through.
- Targets are made up or user-chosen. She does not know what is on the screen.
- A display change is noticed within two seconds, not instantly.
- Mixed scale factors across monitors are handled in the coordinate code and
  tested with made-up layouts; only a single-monitor machine was available to try.
- No lip synchronisation; her mouth opens and closes while she speaks.
- She is not restarted automatically after a crash, to avoid a crash loop.
- Avatar requests bypass nothing, but each costs one audited broker call
  (tens of milliseconds); per-frame work never goes through the broker.

## 9. Later phases (plans, not permission)

Each needs its own decision before work starts.

| Phase | Goal | Extension point already in place | Must exist first |
|---|---|---|---|
| 2 | Real screen awareness: accessibility targeting, contextual positioning, guided demonstrations | `SpatialTargetProvider` with a declared `permission`; `TargetRegistry` revalidation; the six named permissions | Authenticated sessions and approval (ADR-017, pending NEW-A); a decision on what may be read; privacy exclusions; disclosure rules for anything sent to a model (pending NEW-B) |
| 3 | Full 3D rendering, character assets, realistic and holographic materials | `AvatarRenderer`, `RENDERERS`, `choose_renderer`, `Appearance` hints, the JSON vocabulary for an out-of-process engine | Asset and licence review (LIC-006); GPU admission so the avatar yields to models |
| 4 | Lip synchronisation, facial expressions, richer gestures | `SpeechListener`, `Viseme`, `FaceFrame`, `FacialAnimationBackend` | Owner authorisation for any facial-animation model; a speech engine that reports timing |
| 5 | Avatars on other devices, AR, holographic displays | The overlay already talks over a plain message stream, and `DisplayLayout` is not tied to Windows | Node identity and authenticated transport (distributed features are deferred in the baseline) |

Input control (`input.mouse`, `input.keyboard`, `app.action`) is not in any of
these phases. The baseline treats computer use as its own, risk-isolated provider
(PHY-003). Pointing at something never authorises acting on it.
