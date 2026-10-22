# ADR-007: Resource Intelligence and VRAM Management

**Status: recorded from implementation, 2026-10-22. Not approved.** This records what
the code on the release line already decides, so the decision can be read, argued
with and approved or reversed. It does not claim the decision is validated, and no
acceptance test is passed by it. Baseline: *Freya Foundation v1.1*, section 22.

**Baseline summary:** Freya owns policy; runtimes/schedulers provide mechanisms.

## What the code decided

`gpu/resource_manager.py` reads what Ollama and ComfyUI have loaded and can unload
either. Image generation and the large speech engines unload the Ollama models first
when the card is too full, and only one large speech engine is loaded at a time. The
policy (who yields to whom) is Freya's; the unloading is each runtime's own API.

## Departs from the baseline

There is no placement policy beyond "the newcomer evicts the chat model", no
estimate of what a load needs before it starts, and no accounting of what other
programs on the PC hold.

## Validation owed

See ADR-016: reservations before loading, and reconciliation after a crash.
