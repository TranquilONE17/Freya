# ADR-003: Provider Lifecycle and Isolation

**Status: recorded from implementation, 2026-10-22. Not approved.** This records what
the code on the release line already decides, so the decision can be read, argued
with and approved or reversed. It does not claim the decision is validated, and no
acceptance test is passed by it. Baseline: *Freya Foundation v1.1*, section 22.

**Baseline summary:** Replaceable providers with explicit lifecycle/health/failure.

## What the code decided

`ProviderRegistry` (`core/providers/registry.py`) holds each provider's start, stop
and health handlers. A capability is available only while its provider is running and
healthy; Ollama's health is re-checked when a call is unavailable or fails, and a model
Ollama would run on its own servers makes the provider unhealthy. Providers with no
work to do (file reader with no folder open, world view with its program off) report
unhealthy so their tools are not offered. Heavy engines (Chatterbox, Qwen3-TTS) run as
helper processes in their own environments and stop after five idle minutes.

## Departs from the baseline

"Isolation" in the baseline includes failure containment. In-process providers share
Freya's process: a crash or hang in one is Freya's. Only the speech helpers, the
avatar overlay and ComfyUI run as separate processes.

## Validation owed

- A provider replaced without changing callers (the baseline's own freeze gate):
  the obvious candidate is a second model runtime behind `llm.chat`.
- A time limit on every health handler, so one hung check cannot hold a turn.
