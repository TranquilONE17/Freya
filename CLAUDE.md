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
- `src/freya/tools/` — system tools (registered as capabilities), regex router, LLM
  selector/executor.
- `src/freya/gpu/resource_manager.py` — Ollama/ComfyUI VRAM handoff.
- `src/freya/voice/` — faster-whisper STT, Kokoro TTS. `src/freya/image/` — ComfyUI client.

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
the startup model warm-up, and the unwired `tool_selector.py`. `tool_executor.py` is
also unwired and calls the registry, not the broker. `CapabilityDefinition` is far smaller than the
baseline's capability schema; its `destructive`/`requires_gpu` flags are interim.

Audit log: `data/freya_control.db` holds policy rules and the append-only, hash-chained
`audit_event` table. It is verified at startup; if verification fails, the broker
refuses every invocation. Checkpoints of the chain head go to the file named by
`FREYA_AUDIT_CHECKPOINT_PATH` when set, which only adds tamper evidence if that file is
somewhere this machine cannot rewrite. This does not protect against a host
administrator. SQLite durability settings are provisional pending ADR-015; each audited
invocation currently costs roughly 30–60 ms in synchronous writes. Default policy rules
are applied once per named seed (`policy_seed` table), so removed rules stay removed.

`tests/` covers the registries, tool modules, policy, audit, broker, and model runtime,
using a fake Ollama client (`tests/conftest.py`); `voice/stt_test.py` and
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
