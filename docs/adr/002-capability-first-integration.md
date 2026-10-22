# ADR-002: Capability-First Integration

**Status: recorded from implementation, 2026-10-22. Not approved.** This records what
the code on the release line already decides, so the decision can be read, argued
with and approved or reversed. It does not claim the decision is validated, and no
acceptance test is passed by it. Baseline: *Freya Foundation v1.1*, section 22.

**Baseline summary:** No direct cross-module implementation coupling.

## What the code decided

A feature reaches another through a named capability invoked on `CapabilityBroker`
(`core/capabilities/broker.py`): policy is checked, availability is checked, a
dispatch row is written, the handler runs, the outcome is written. The model reaches
tools only through `ModelToolHost` (`tools/model_tools.py`), which offers only
capabilities marked `model_tool` and never destructive ones. Conversation recall,
cloud delegation, the model record, file reading and world view all follow this.

## Departs from the baseline

`assistant.py`, `conversation_memory.py`, `memory_manager.py` and the evaluation
runner import `freya.memory` directly; `main.py` imports most packages. The window's
Voice and Media tabs call their services directly and are not policy-checked or
audited (CLAUDE.md, "Voice studio").

## Validation owed

- An import-graph test listing the allowed direct imports, so new coupling fails.
- The voice studio and media services behind capabilities before multi-user.
