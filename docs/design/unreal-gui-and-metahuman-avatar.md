# Design proposal: an Unreal Engine desktop GUI with a MetaHuman avatar

**Status: proposal, written 2026-10-08. Nothing here is implemented, installed, or
approved.** It does not approve any ADR, freeze the architecture, or assign
requirement IDs. New requirements carry provisional labels **NEW-AC to NEW-AJ**,
continuing from NEW-A to NEW-L (pending amendments) and NEW-M to NEW-AB (the
development design); no existing ID is reused. Baseline references (ARCH-, GUI-,
CAP-, SEC-, RES-, LIC-, EXT-, OPS-, PROV-) are to *Freya Foundation v1.1*.
ADR-017 (gateway authentication) is pending and this design depends on it.

Each statement below is marked **[Verified]** (checked today, with how),
**[Recommend]** (a design choice), or **[Experiment]** (unknown until tried).

> This document was cut short by a usage limit. Sections 1 to 6 and 10 to 12 are
> complete. Sections 7 to 9 (avatar assets, performance and distribution, the full
> GUI function inventory) are outlines to be filled in. See "What is not done".

## 1. Direction (from the owner)

1. Unreal Engine becomes the proposed main desktop GUI: one ordinary resizable
   window with a MetaHuman-style avatar beside chat and controls, portrait and
   full-body views, optional always-on-top. The floating transparent desktop
   avatar, click-through, desktop walking, and pointing outside the window are
   **deferred**.
2. The Python backend stays independent and owns reasoning, memory, models, tools,
   permissions, audit, images, and voice generation. Unreal presents, takes input,
   animates, and plays coordinated speech. The web GUI stays as a fallback. Freya
   must work with no Unreal and no avatar.
3. MetaHuman is the first avatar, not the only one. VRM and lightweight renderers
   are preserved; identity, asset format, renderer, and presentation settings are
   separated; renderers report their features.

This fits the baseline: "Freya has no inseparable canonical GUI" (section 14),
GUI-001 (several GUIs, no duplicated state), GUI-004 (GUIs are untrusted, limited
clients), ARCH-001 (every GUI is replaceable).

## 2. What was checked

| Fact | Status |
|---|---|
| The plugin repository `isundahl/LLM_Plugin` is Apache-2.0, created 2026-07-30, last pushed 2026-09-07, 14 commits, 5 stars, Win64 only, marked beta (0.2.0-beta). | **[Verified]** GitHub API and README |
| Its descriptors name **Unreal Engine 5.8**. | **[Verified]** `.uplugin` |
| The MetaHuman bridge is about 26 KB of C++ in one component. It contains **no characters, animations, maps, models, or voice weights**; the README says so, and the repository excludes "demo map and MetaHuman assets". | **[Verified]** source read |
| The bridge is a thin layer over **Epic's own** real-time audio solver: it subclasses `FMetaHumanAudioBaseLiveLinkSubject` and `FMetaHumanLocalLiveLinkSource` (modules `MetaHumanLocalLiveLinkSource`, `MetaHumanCoreTech`, `MetaHumanPipelineCore`; plugins `LiveLink`, `MetaHumanLiveLink`, `MetaHumanCoreTech`), pushes PCM with `AddAudioSample`, and publishes Live Link curves the MetaHuman face reads. | **[Verified]** source read |
| It feeds 20 ms frames, uses a solver lookahead of 80 to 240 ms, warms the solver with 1 s of silence at 24 kHz mono, and delays audible playback separately from the solver so lips and voice can be aligned. | **[Verified]** source read |
| The bridge depends on the plugin's own TTS component and audio types (`ULocalLLMTextToSpeechComponent`, `FLocalLLMAudioChunk`). It cannot be used without the main plugin as written. | **[Verified]** `Build.cs`, headers |
| The author does **not** claim packaged builds work: "Test a cooked Win64 build using the exact Unreal/MetaHuman version intended". | **[Verified]** README |
| Unreal Engine 5.8 has been released. | **[Verified, weakly]** a repost of Epic's announcement; not read on Epic's site |
| Epic documents real-time MetaHuman animation from audio through Live Link from UE 5.6, and says it is "computationally heavy" and needs the GPU. | **[Verified]** Epic documentation, via search |
| Kokoro, Freya's voice, produces 24 kHz mono float audio: the same form the bridge warms the solver with. | **[Verified]** `voice/tts.py` |
| On this PC: Epic Games Launcher is installed; **no Unreal Engine is installed**; Visual Studio 2026 Community with MSVC 14.51 is installed; 1.3 TB free; RTX 4090 with 24 GB, 3.6 GB in use when idle. | **[Verified]** looked today |
| The Fab listing page and Epic's EULA page **could not be read** (both refuse automated readers). Nothing in this document relies on the listing. | **Not verified** |
| MetaHuman and Unreal content may not be used to train or test AI systems. | **Reported by secondary sources and translated Epic pages; the English clause was not read.** Owner to confirm. |
| Unreal is free for individuals and businesses under USD 1 million a year; a 5% royalty applies to a distributed product's revenue above USD 1 million; from UE 5.6 MetaHumans fall under the Unreal Engine EULA. | **Reported by Epic's licence page via search; not read directly.** |

**Conclusion on the plugin. [Recommend]** Treat the MetaHuman bridge as
**reference code**, not a dependency. What Freya needs from it is about 150 lines:
the Live Link subject that accepts PCM, the source that creates it, and the
playback-delay idea. Write Freya's own small Unreal module that does this with
Freya's audio, keeping the Apache-2.0 notice for anything adapted (LIC-001,
LIC-004). Do not take the main plugin: it brings its own LLM, speech recognition,
speech synthesis, and 3 GB of models, all of which Freya already has.

## 3. Where the code is today

| Area | Today | For this design |
|---|---|---|
| `AvatarHost` | Starts an overlay process, talks JSON lines over pipes, survives its crash, kills it on stop. | **Reuse the pattern** for starting and supervising Unreal. The pipe protocol itself is not reused: Unreal is a full GUI client and goes through the gateway. |
| `AvatarService` | Three display capabilities plus library, search, prepare; every request is a broker call; settings per user; an off switch. | **Keep.** Unreal's avatar requests go through the same broker calls. |
| `AvatarModel` | Size limits, boundaries, placement beside a target, pointing geometry on the desktop. | **Mostly not needed** inside a window. Useful parts: expression state, speaking state, wave, the animator's priorities and interruption. Desktop placement and pointing stay for the deferred floating avatar. |
| Renderer selection | `RENDERERS`, `choose_renderer`, `on_request`; `tk-placeholder`, `null`, `web`. | **Extend** with a feature report (section 6). |
| Avatar profiles | `AvatarLibrary`: a profile is a name and the SHA-256 of a VRM file. | **Generalise** (section 6). VRM-specific today. |
| Speech events | `FreyaVoice` synthesises a sentence with Kokoro and plays it itself with `sounddevice`; a listener hears started, completed, interrupted, and a constant level. | **Change** (section 5): audio must be able to go to a client, and "speaking" must mean what is actually audible. |
| Gateway | Loopback HTTP and one WebSocket; Host, Origin, and cookie checks; a single-use key in the address; per-window queue; no version, no client identity, no scopes. | **Extend** into a versioned protocol with a handshake (section 4). |
| Shutdown | Ordered: gate closed, windows stopped, turn drained, then voice and control database. Console-free mode exits 8 s after the last window closes so the microphone is never left open unseen. | **Keep the order; generalise** "window" to "client". |
| GPU coordination | `GPUResourceManager` unloads Ollama models for ComfyUI and for a large speech engine. No accounting of anything else. | **Extend**: Unreal becomes a known consumer (section 8). |
| Review finding: bounded archive extraction | **Not fixed. [Verified]** `converter.unpack` checks declared sizes for `.zip` before extracting, but for `.7z` and `.rar` it runs `tar -xf` and checks size, count, and links only **afterwards**, limited by a 10-minute timeout alone. A hostile archive can fill the disk before the check. | Fix before any work that adds more import paths: list with sizes first, refuse over the limits, and watch the folder while extracting. |
| Review finding: verified avatar content identities | **Not fixed. [Verified]** `AvatarLibrary.scan` takes a model's SHA-256 and licence from a cache in `avatar_library.json` when the file's name, size, and modified time match, without checking the cached entry's shape or re-hashing. `model_bytes` and `active_model_path` hand out the file without confirming it still has that hash. A file swapped in place, or an edited cache, gives one model another's identity and licence confirmation. | Fix by hashing at the point of use, or by keeping accepted models in a content-addressed, read-only store. Section 6 depends on this. |

## 4. Backend communication and lifecycle

**[Recommend]** Unreal is a client of the Client Gateway like the web page, not a
special path. One protocol, two clients (GUI-001, GUI-002).

**NEW-AC (proposed, MUST).** A GUI client presents to the user and collects input.
It holds no personal database, secret, model, or capability handler, and reaches
Freya only through the Client Gateway. Every request it makes that has an effect
is carried out by a broker invocation in the backend, attributed and audited
there (GUI-004, ARCH-019).

**Protocol.** Version 1 formalises what the window already does.

- Transport: the existing loopback HTTP and WebSocket (GUI-008). Text frames are
  JSON objects with `type`; binary frames are used only for audio and uploads.
- Handshake: the client's first frame is
  `hello {protocol: 1, client: {kind, name, version}, features: [...]}`. The
  server answers `welcome {protocol, server_version, features, limits, session}`
  or `refused {reason}` and closes. Unknown required features are refused, not
  ignored (GUI-012).
- Limits, stated in `welcome` and enforced by the server: frame size, message
  rate, upload size, audio buffer, text length. The existing limits (4,000
  characters of chat, the upload cap) become part of this.
- Events carry a sequence number; a reconnecting client sends the last one it saw
  and is told to resynchronise if it is too old (GUI-013).
- Existing message types keep their meaning: `say`, `image`, `command`, `mute`,
  `volume`, `interrupt`, `status`, `voice`, `avatar`, `memory`. New: `speech.*`
  (section 5), `client.state` (visible, minimised, hidden), `ping`/`pong`.
- The web page moves to the same handshake. There is one server-side
  implementation of each function, so the two GUIs cannot disagree; a client
  contains layout and nothing else.

**Authentication. [Recommend], subject to ADR-017.** Today's single-use key in the
address is acceptable for a browser Freya opens herself but conflicts with GUI-009
("never put bearer tokens in URLs") as a general mechanism.

- When Freya starts Unreal, she passes a single-use pairing secret **on the child
  process's standard input**, not on the command line or in the environment (both
  are visible to other programs of the same user). Unreal exchanges it once for a
  session token, held in memory only.
- A client Freya did not start must be approved by the owner in an already
  trusted place (GUI-009). Not in the first milestones.
- Each client kind gets a **scope**: the set of message types it may send. The
  Unreal client's scope is the web page's scope plus `speech.*`. It is not a way
  to name capabilities directly.
- This is still not user authentication: turns remain attributed to the fixed
  `local-owner` principal until authenticated sessions exist (GUI-014).

**NEW-AD (proposed, MUST).** Exactly one party owns Freya's lifecycle. In the
alpha it is the Python backend: it starts first, starts the chosen GUI, and
decides when to exit.

- Setting `gui = unreal | web | none`. `unreal` falls back to `web` with a notice
  if Unreal is not installed or fails to start twice.
- Readiness: Unreal is "ready" when its handshake completes, within a time limit;
  the web window opens meanwhile only if the owner has chosen that.
- Heartbeat: ping every 5 s; a client silent for 15 s is treated as gone.
- Crash or disconnect: speech playback returns to the backend at once (section
  5); Unreal is restarted with backoff, at most three times, then the web window
  is offered.
- **Closing Unreal** follows one explicit policy, the owner's choice (decision
  U2): *exit with the window* (today's console-free behaviour, 8 s after the last
  client goes) or *keep running*. If Freya keeps running with no client
  connected, the microphone is **muted until a client returns**, so it is never
  open unseen. With a console attached, today's behaviour is unchanged.
- Shutdown order is unchanged, with "window" read as "every client"; Unreal is
  asked to close, given a few seconds, then ended with its process family.

**Threads. [Recommend]** In Unreal all network reading, JSON parsing, and audio
decoding happen off the game thread; the game thread receives small, already
parsed messages through a queue and never waits on the backend.

## 5. Speech and facial animation

**NEW-AE (proposed, MUST).** At any moment exactly one party plays Freya's voice
aloud: the backend, or one client that asked for it and was granted it.

- A client asks for playback with the `speech.playback` feature in its `hello`.
  The backend grants it to at most one client and records which. With no such
  client, or when that client disconnects, the backend plays, as now.
- If the playing client vanishes mid-sentence, that sentence is abandoned and the
  backend speaks the remaining sentences. Nothing is played twice.

**Format and transport.**

- Audio as synthesised: 24 kHz, mono, 16-bit PCM. No resampling by Freya.
- Per sentence: `speech.start {utterance, sample_rate, channels, text}`; then
  binary frames, each with an 8-byte header (utterance number, sequence number)
  and at most 100 ms of audio; then `speech.end {utterance, samples}`.
- The client answers `speech.started`, `speech.finished {utterance, samples}`, or
  `speech.interrupted`.
- Bounds: at most 30 s of audio per sentence and 60 s queued in total; beyond that
  the backend waits. A frame out of sequence ends the utterance with an error.
- `speech.cancel` empties the client's queue, resets the solver, and returns the
  face to neutral.

**NEW-AF (proposed, MUST).** Freya counts herself as speaking from the first
audio sent until the playing client reports the sentence finished or interrupted,
or a deadline of the sentence's length plus a short margin passes. The microphone
is ignored for exactly that time.

Today `FreyaVoice.is_busy()` is true while the backend's own player runs; with
Unreal playing it must follow the client's reports instead, or Freya would hear
herself.

**NEW-AG (proposed, MUST).** Audio sent for facial analysis is at full level.
Volume is applied only where sound is made audible.

Today `FreyaVoice` scales the samples by the volume before playing. For a client,
the unscaled audio and the volume are sent separately, so a quiet voice still
articulates fully.

**In Unreal. [Recommend]** A small Freya module, modelled on the reference bridge:
a Live Link subject fed from a queue at real-time pace, the solver warmed with
silence at start, and audible playback delayed by a calibrated amount so the
voice does not lead the lips.

**[Experiment]**

1. Does Epic's audio solver run in a **packaged** build, not only the Editor? The
   reference author does not say it does. This is the single largest risk and is
   the first thing milestone 1 must prove.
2. Whether the solver accepts 24 kHz directly in 5.8 (the reference feeds it so).
3. The lookahead and playback delay that look right with Kokoro's voice.
4. Blending: the solver drives jaw, lips, and tongue; expressions are layered on
   the upper face, and on the mouth corners at reduced strength, so a smile does
   not fight the lip shapes. Whether this looks right needs trying.
5. Neutral recovery: after `speech.finished` or a cancel, ease all speech curves
   to zero over about a quarter of a second.
6. The solver's GPU cost beside Ollama.

## 6. Avatars: identity, asset, renderer, presentation

**NEW-AH (proposed, MUST).** Four things are recorded separately:

1. **Identity**: who the avatar is (a name, an id). One identity may have several
   assets.
2. **Asset**: one concrete form of it, with a `format` (`vrm`, `metahuman`,
   `placeholder`), where it is, a content digest, and its licence record.
3. **Renderer**: what draws it (`tk-placeholder`, `web`, `unreal`), chosen by
   what is installed and what the asset's format needs.
4. **Presentation**: view (portrait, full body), always-on-top, quality, size.

A MetaHuman asset is **not** squeezed into the VRM fields: it has no single file,
no VRM licence block, and no VRM expression list.

**NEW-AI (proposed, MUST).** A renderer reports its features and the GUI shows
only controls for those: expressions, lip sync from audio, portrait and
full-body views, gestures, appearances, pointing on the desktop, click-through.

**How MetaHuman differs from VRM. [Verified in part]**

- A VRM is one file the owner drops in a folder; Freya reads its description and
  shows it immediately.
- A MetaHuman is made in MetaHuman Creator inside the Unreal Editor, assembled,
  and **cooked into the Unreal build**. Adding or changing one means editor work
  and a rebuild, or a separately built content pack. Freya cannot import one at
  run time. Arbitrary run-time import is later work, and may never be practical.
- So "switching character" means choosing among characters in the installed
  pack, each listed in an asset manifest with a digest (LIC-006, EXT-006).

**NEW-AJ (proposed, MUST).** An asset's identity is the digest of its content,
checked when it is accepted and again when it is used. A cached record is never
enough on its own. (This is the open review finding, made a requirement.)

## 7. Avatar assets and animation (outline; not finished)

- One character, one outfit, to start. Needs: MetaHuman Creator work by the
  owner or under the owner's direction, clothing and hair chosen from what the
  licence allows, a simple lit backdrop, the optimised assembly for run time.
- Animation plan: idle with breathing and weight shifts; blink; gaze toward the
  chat or the user; listening, thinking, and speaking states driven by Freya's
  existing events; the five expressions; wave; in-window gestures.
- Body animation needs source animations. **The reference plugin includes none**
  and expects Unreal's own template assets. Their licence for this use must be
  checked.
- Later: wardrobe editing, more characters, run-time import.

## 8. Performance and distribution (outline; not finished)

- **[Experiment]** Measure Unreal beside Ollama (`gpt-oss:20b`), Whisper, Kokoro,
  and ComfyUI on the 24 GB card. A MetaHuman with strand hair and the audio
  solver may not fit beside the model at full quality.
- Quality levels; frame caps (lower when idle, lower still when unfocused);
  minimised or hidden: stop rendering.
- **Stopping rendering does not free VRAM.** Only unloading the character or
  closing Unreal does. The GPU manager needs a real "release" request to Unreal
  for image generation, with confirmation (RES-001, RES-010).
- Packaged Windows build as an optional install, outside the Python package;
  source in the repository, large assets and build output outside it; an asset
  manifest with digests; third-party notices; a protocol version check at
  connect; update and rollback by keeping the previous build (OPS-001, EXT-007).
- Offline after setup must be verified on a disconnected run.
- Other platforms and nodes: Win64 only is promised. The reference is Win64
  only.

## 9. GUI migration (outline; not finished)

- Native UMG is the eventual direction; an embedded web view inside Unreal is the
  fallback for functions not yet migrated. **[Experiment]** UMG's handling of long
  selectable, copyable, scrolling chat text, DPI scaling, keyboard navigation,
  and screen readers (Epic documents screen reader support for common widgets
  only) must be tried before committing.
- The full inventory (chat streaming, images, voice studio, recordings and
  uploads, settings, console, status, avatar controls, memory, cancellation,
  exit) and its mapping is **not yet written**.

## 10. Milestones

Effort is in working days and is rough. Owner time for installs and character
creation is separate.

| | 1. Packaged feasibility prototype | 2. Integration | 3. GUI migration | 4. Animation and release |
|---|---|---|---|---|
| Contains | One MetaHuman, a transcript, a text box, connected to the real backend; Freya's own speech moving the face, in a **packaged** build | Streaming, cancel, reconnect, renderer choice, lifecycle, GPU release | Functions moved one at a time; web fallback kept | Expressions, gestures, polish, offline check, install, rollback |
| Depends on | UE 5.8 installed (owner), a MetaHuman made (owner), protocol v1 handshake, `speech.*` | Milestone 1 passing; the two review fixes | Milestone 2; UMG experiment | Milestone 3 |
| Accept when | Typed text gets a real reply; lips match audio within a judged tolerance; mic ignores her own voice; works with the Editor closed | Kill Unreal mid-sentence: backend finishes speaking, mic state right, Unreal returns; image generation gets its VRAM back | Each function works in both GUIs from one backend implementation | Disconnected run works; install and rollback rehearsed |
| Tests | Protocol tests with a scripted client; audio framing and bounds; playback-owner hand-over | Crash, disconnect, slow client, refused version | Per-function contract tests run against both clients | Offline run; version mismatch; rollback |
| Main risk | Solver does not run packaged | VRAM does not fit | UMG text and accessibility fall short | Animation quality |
| Effort | 6 to 12 | 8 to 15 | 20 to 40 | 15 to 30 |

**If the solver does not run in a packaged build**, the choices are: ship with the
Editor runtime (not acceptable for distribution), use a different lip-sync
source, or keep the web renderer. That is why it is tested first.

## 11. Installs and downloads

| Needed | Have it? | Who |
|---|---|---|
| Unreal Engine 5.8 (tens of GB) | No | Owner: system software |
| MetaHuman plugins and Creator content | No | Owner, through Epic's launcher |
| Visual Studio with C++ game workload | VS 2026 with MSVC present; workload not checked | Owner if missing |
| Epic account, EULA acceptance | Owner's | Owner only |
| The Fab plugin | Not needed under this recommendation | None |

## 12. Decisions that need the owner

| # | Decision | Recommendation |
|---|---|---|
| U1 | Accept the Unreal Engine EULA and confirm its MetaHuman and AI-training terms by reading them | Owner only; I could not read the page |
| U2 | When Unreal closes: Freya exits, or keeps running with the microphone muted | Exit, as today |
| U3 | Use the bridge as reference code, not as a dependency | Yes |
| U4 | Fix the two open review findings before milestone 1 | Yes |
| U5 | Install Unreal Engine 5.8 and make the first character | Needed before milestone 1 |
| U6 | Whether Freya may ever be distributed commercially (changes licence obligations for every asset) | Decide before choosing clothing, hair, and animations |

## What is not done

- Sections 7, 8, and 9 are outlines.
- The Fab listing and Epic's EULA were not read directly.
- No measurement of any kind has been made; Unreal is not installed.
- No code was changed.
