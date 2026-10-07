# Freya — project guide for Claude

Freya is a local-first, modular, multi-user agentic AI platform. The alpha targets a
single Windows 11 workstation (RTX 4090); the architecture must later scale to a
heterogeneous Linux/Windows rack without changing Core contracts.

## Architecture documents

- **Authoritative baseline:** *Freya Foundation v1.1 — System Architecture and Design
  Specification* (the owner's reconciled v1.1), at
  `docs/specs/Freya_Foundation_v1.1_baseline.docx`. Read it before making architecture
  decisions.
- **Pending amendments:** `docs/specs/Freya_Foundation_v1.1_Claude_amendments_redline.docx`
  — tracked-change proposals (NEW-A to NEW-L) awaiting Codex review and reconciliation.
  Not yet adopted.
- **Superseded:** `docs/specs/Claude_proposal_superseded.docx` — an earlier proposal.
  Reference only. Its requirement and ADR IDs collide with the baseline; never cite them.

Rules for the spec:
- Never renumber requirements or reuse an existing requirement/ADR ID for a new meaning.
  New proposals carry provisional labels (NEW-x) until reconciliation assigns IDs.
- ADR-001 to ADR-018 are pending completion and approval. Do not describe any ADR as
  approved, the architecture as frozen, or any acceptance test as passed unless the
  owner says so.
- Agreed decisions (change only with an explicit, justified proposal): Hyper-V as the
  preferred Windows alpha isolation profile (untrusted execution disabled until
  validated); SQLite alpha persistence behind replaceable contracts; loopback
  HTTP/WebSocket alpha gateway profile; Ollama as a replaceable model runtime;
  configurable 24h RPO / 4h RTO / 24h purge / 30-day retention targets; SEC-035
  federated sovereignty; deferred features stay disabled.

## Repository layout (current)

- `src/freya/main.py` — CLI entry point (text, voice, image commands).
- `src/freya/control_plane.py` — assembles providers, capabilities, policy, audit, and
  the broker for the single-workstation alpha.
- `src/freya/providers/model/ollama.py` — the `ollama-local` provider and its
  `llm.chat`, `llm.chat_stream`, and `llm.embed` capabilities.
- `src/freya/core/` — `assistant.py`, `llm.py` (memory prompts; model calls go through
  `model_runtime.py`, which asks the broker),
  `capabilities/` (CapabilityRegistry, CapabilityBroker), `providers/`
  (ProviderRegistry), `policy/` (deny-by-default SQLite policy engine), `audit/`
  (hash-chained SQLite audit log, checkpoint sinks), `persistence/` (ControlStore and
  its migrations).
- `src/freya/memory/memory_manager.py` — SQLite memory with embeddings and history.
- `src/freya/tools/` — read-only system tools registered as capabilities (host info,
  GPU, CPU, RAM, all drives, a Windows-only hardware inventory in
  `hardware_inventory.py`, and temperatures/fans/power in `sensors.py`);
  `model_tools.py` (`ModelToolHost`, which offers marked
  capabilities to the model and runs the ones it asks for); `tool_router.py` (regex,
  image requests only). A tool added after first release needs its own named policy
  seed in `control_plane.py`. Its description is what the model chooses by, so say
  what it returns and when to prefer a neighbouring tool.
- `src/freya/gpu/resource_manager.py` — Ollama/ComfyUI VRAM handoff.
- `src/freya/voice/` — faster-whisper STT, Kokoro TTS, `wake.py` (deciding whether a
  heard sentence is addressed to Freya), `listener.py` (utterance segmenting, the
  attention window, and the background listener thread).
- `src/freya/gateway/` — `server.py` (the loopback gateway: HTTP GET for the page and
  images, one WebSocket for everything interactive) and `static/` (the window's page:
  Chat and Images tabs). `src/freya/window.py` — opens that page in a standalone Edge
  app window with its own browser profile, and builds the status strip.
  `src/freya/events.py` — the event bus the console loop publishes to and the window
  subscribes to. `src/freya/image/gallery.py` — Freya's own copies of generated images
  in `data/images/`.
- `src/freya/hands_free.py` — starts background listening and handles `/mute`,
  `/unmute`, `/names`, `/name add|remove`. `src/freya/settings.py` — owner preferences
  in `data/freya_settings.json` (currently the names Freya answers to).
  `src/freya/turn_gate.py` — lets one turn run at a time, typed or spoken.
- `src/freya/image/` — ComfyUI client. `src/freya/providers/image/comfyui.py` — the
  `comfyui-local` provider. When an image is requested and ComfyUI is not answering,
  Freya runs the ComfyUI server that Comfy Desktop installed, directly and with no
  window (the Desktop app waits for a click before starting its server), using the
  app's own model-path config and shared input/output folders. Output goes to
  `data/comfyui_server.log`. Freya stops that server when she exits, and a Windows job
  object ends it if her process dies without a normal exit; she never stops a ComfyUI
  the owner started. `FREYA_COMFYUI_COMMAND` overrides how it is started. The
  paths inside Comfy Desktop's install are discovered, not documented by its vendor, so
  an app update could move them. Image generation itself still calls ComfyUI directly,
  not through the broker.

Known state: the system tools and every chat and embedding call run only through
`CapabilityBroker`, which checks policy (deny by default), checks availability, writes
an audit record before executing, and records the outcome (for a streamed reply, when
the stream ends). A capability is available only while its provider is running and
healthy; the Ollama provider's health is re-checked when a model call is unavailable or
fails. The broker attributes everything to a fixed `local-owner` principal because
there are no authenticated sessions yet. `core/llm.py` and `memory_manager.py` reach the
model through a process-wide `ModelRuntime` set up by `build_local_control_plane()`, so
the control plane must be built before `FreyaAssistant`. Still calling their backends
directly: Whisper, Kokoro, ComfyUI, the memory store, the GPU manager's Ollama unload,
and the startup model warm-up. `CapabilityDefinition` is far smaller than the
baseline's capability schema; its `destructive`/`requires_gpu` flags are interim.

Model tool calling: `FreyaAssistant.respond_stream` offers the model the capabilities
whose metadata has `model_tool: True` (never destructive ones) using the model's native
tool calling. Requested tools run through the broker, their JSON results go back to
the model, and it answers in its own words; at most three tool rounds per turn. The
offered tools take no arguments, and arguments the model invents are discarded. Tool
results are untrusted content from the model's point of view. The tool exchange is not
kept in conversation history. Before adding a tool that takes arguments or has effects,
decide how its arguments are validated and authorized.

Always-on listening: the microphone stays open on a background thread while the
keyboard prompt waits. Every utterance is transcribed locally and then discarded unless
it is addressed to one of Freya's names at the start or end of the sentence; the name
alone opens a ten-second window for one follow-up sentence. Typed turns run on the main
thread and spoken turns on the listener thread, serialized by `TurnGate`, which is why
the memory database connection allows cross-thread use. The microphone is ignored
while Freya is speaking or handling a turn; she cannot be interrupted by voice. Voice
is ambient input and is not authentication: before any tool with effects exists,
decide what spoken requests may trigger (see proposed NEW-I).

The window: Freya opens it at startup (`FREYA_WINDOW=0` disables that; `/window`
reopens it). The gateway binds `127.0.0.1` only, port 8770 or a free one. A request is
accepted only with a matching Host header and a session cookie, which is issued once in
exchange for a single-use key in the address Freya opens; the WebSocket also requires
this server as its Origin. This is a first step, not the authenticated gateway of the
baseline: there is no pairing, no per-client scope, and window turns are attributed to
the same fixed `local-owner` principal. The page shows everything with `textContent`
and a strict Content-Security-Policy, because replies and tool results are untrusted.
The window can only ask for a chat turn, an image, mute/unmute, or stopping speech;
add new message types deliberately. `main.py` publishes conversation and image events
on a module-level `EVENTS` bus; the console still prints as before.

Audit log: `data/freya_control.db` holds policy rules and the append-only, hash-chained
`audit_event` table. It is verified at startup; if verification fails, the broker
refuses every invocation. Checkpoints of the chain head go to the file named by
`FREYA_AUDIT_CHECKPOINT_PATH` when set, which only adds tamper evidence if that file is
somewhere this machine cannot rewrite. This does not protect against a host
administrator. SQLite durability settings are provisional pending ADR-015; each audited
invocation currently costs roughly 30–60 ms in synchronous writes. Default policy rules
are applied once per named seed (`policy_seed` table), so removed rules stay removed.

`tests/` covers the registries, tool modules, policy, audit, broker, model runtime,
name matching, the listener, and the listening commands, using a fake Ollama client
(`tests/conftest.py`) and scripted microphone blocks; `voice/stt_test.py` and
`voice/tts_test.py` are manual scripts, not automated tests. `memory_manager.py` locates
`data/` relative to the source tree, so it only works from an editable install.

## Running locally (Windows)

- Python 3.12 virtual environment at `.venv`.
- `freya` is an installable package (src layout) and imports are absolute
  (e.g. `from freya.core.llm import ...`). It is installed in `.venv` in editable mode;
  run it from any directory with `freya` or `python -m freya`.
- Requires Ollama on `127.0.0.1:11434` with `gpt-oss:20b` and `nomic-embed-text`.
  Image generation requires ComfyUI on `127.0.0.1:8188`.
- Direct dependencies are declared in `pyproject.toml`; `uv.lock` pins the full resolved
  set for Windows and Linux (Python 3.12). After changing dependencies, run `uv lock`
  and commit both files. `uv sync` rebuilds `.venv` from the lock.
- Run the tests with `python -m pytest` from the repository root (pytest is in the `dev`
  dependency group).
- Optional: `system.sensors` reads LibreHardwareMonitor (MPL-2.0, installed by the
  owner with winget, not bundled) over its local web server at
  `http://127.0.0.1:8085/data.json` (`FREYA_SENSOR_URL` overrides). It must be running
  as administrator with Options > Remote Web Server > Run enabled; otherwise the tool
  reports that sensors are unavailable.
- Kokoro also needs the spaCy model `en_core_web_sm`, which is downloaded outside the
  lockfile.

## Working rules

- Work on a branch and open a pull request; never commit directly to `main`.
- `data/freya_memory.db` holds the owner's personal memories. Never commit it, print its
  contents, or change its schema without first making a backup copy.
- `data/freya_control.db` holds policy and the audit log. Never edit or delete its
  rows, drop its triggers, or change shipped entries in `MIGRATIONS`; add a new
  migration instead. Policy changes are owner actions.
- No secrets, API keys, or tokens in code, config, commits, or logs.
- Generated or untrusted code must never run inside Freya Core or with access to Core
  storage or credentials (ARCH-017).
- Agents must not modify Freya's own policy, configuration, or Core code as a side effect
  of a task; changes go through review (proposed NEW-D).
- Ask before installing system software, enabling Windows features (e.g. Hyper-V), or
  changing ACLs or service accounts — these are owner actions.
- Keep the existing code style; repository files use LF line endings.

## Next planned work (alpha step 1)

Done: `pyproject.toml`, the lockfile, the package layout, tests for the registries, the
`ToolRegistry` merge, linking provider health to capability availability, and the SQLite
audit log and policy table in front of capability execution.

Also done: Ollama behind a provider, with chat and embeddings through the broker.

Not yet started: routing the voice, image, and memory paths through providers and
the broker; authenticated sessions to replace the fixed `local-owner` principal; a
dedicated Windows service identity and ACLs for the control database (owner action); an
off-host checkpoint sink.
