# Delegating work to cloud models

Status: design proposal for the owner's review, written 2026-10-09. Nothing here is
built. It records the owner's decisions of that day and what follows from them. It
adopts no requirement or ADR; the Foundation v1.1 baseline remains authoritative, and
sending anything to an outside model is escalation under ESC-001 to ESC-006.

## Owner decisions

1. Delegation means all available models, local and cloud.
2. Providers: OpenAI and Anthropic first. Any other provider must be connectable the
   same way, without changing Core.
3. Cloud work uses the owner's subscription plans. No money is spent outside them.
   Paid API routes are built but every money cap starts at zero, so no paid call can
   be made until the owner raises a cap.
4. API keys are kept in Windows Credential Manager.
5. What may leave the machine is set per kind of material, starting strict.
6. Approval is by standing rules: kinds of task approved in advance for a provider.
7. A spoken request may start cloud work, after a confirmation the owner clicks in
   the window.
8. Freya tracks each provider's own limits and reset times, weighs cloud use against
   the value of the task, paces weekly allowances across the days, and offers the
   choice to go over when a cap is near.

## Routes

A route is one way of reaching one model: a provider, a model, and how it is paid for.

| Route kind | How Freya connects | What is limited |
|---|---|---|
| Local | Ollama on this PC | VRAM and time |
| Plan | The vendor's own program (`claude`, `codex`), which holds the sign-in | Usage windows set by the vendor |
| API | HTTPS with a key from Credential Manager | Money and requests per minute |

Each cloud route is its own provider (`anthropic-api`, `anthropic-plan`, `openai-api`,
`openai-plan`) with its own capabilities, so policy allows or denies each one
separately and the audit log shows which route served each call. No cloud capability
is ever in a default policy seed: the owner adds the rule. A new vendor is a new
provider module plus a price table and a list of limits; nothing else changes.

The existing roles (`conversation`, `background`) stay local. Cloud routes are reached
only by delegation: a task Freya hands over, not her ordinary replies.

Plan routes drive a program that can read files and run commands by itself. Freya
starts it with no tools, no file access beyond what she passes in, and a filtered
environment (`child_environment.py`), and treats its reply as untrusted text.

## What may leave the machine

Every delegated request is assembled from labelled parts, using the source labels the
context system already carries. Each kind has a setting: allowed, ask first, or never.

| Kind | Starting setting |
|---|---|
| The request itself | Allowed |
| Live conversation | Ask first |
| Stored memories | Never |
| Past conversations and summaries | Never |
| Tool results from this PC | Ask first |
| Files and media | Ask first |
| Freya's own code | Ask first |

A part marked never is left out before the request is built, not filtered afterwards.
Before sending, Freya shows a description (which kinds, how much, which route, the
estimated cost) with the full text one click away. Settings are changed by the owner
in the window, never by voice or by a model, and every change is audited. Only the
minimum the task needs is sent (ESC-005).

## Approval

A standing rule names a kind of task, the routes it may use, the kinds of material it
may send, and its own usage limit. A task that matches a rule goes without asking. A
task that matches none is described to the owner as ESC-004 requires (why local is not
enough, what would leave, which route, the cost) and waits for a yes that covers that
task only.

The prompt offers four answers: allow once, allow for this conversation, allow
permanently, and deny. "This conversation" lasts for the current run of Freya and is
kept in memory only. "Permanently" creates a standing rule for exactly what was shown:
that kind of task, that route, and those kinds of material, with a plan limit of its
own. It is listed in the window, where the owner can remove it. No answer can send a
kind of material whose setting is never, and a later task that wants more than a rule
covers asks again.

Deciding which rule a task matches is done by Freya's code from the task's declared
kind and the labels on its parts, never from a model's say-so. A task that picked up
untrusted content (a web page, a file, a tool result) cannot widen what it sends.

Voice: a spoken request can propose cloud work, including work a standing rule covers.
It is held until the owner clicks the confirmation in the window. Speech never
confirms, changes a rule, changes a setting, or raises a cap.

## Limits and pacing

Freya keeps a ledger per route in the control database (a new migration): each call's
estimated and reported usage, each limit, how much of it is used, and when it resets.

- **API routes.** Usage and remaining rate limits are read from each reply. Cost comes
  from a price table per model; a model with no price is refused. Money caps exist
  per call, per task, per day, and per month, and all start at zero: a call whose
  estimated cost is above zero is refused, and near-cap offers to go over do not apply
  to a zero cap. Only the owner raises a cap, in the window. The month follows the
  provider's billing period, not the calendar.
- **Plan routes.** Vendors do not publish an exact meter. Freya counts what she sends,
  records every "limit reached, resets at" notice, and takes window lengths and reset
  times from the provider. Her figure is an estimate and is shown as one.
- **Pacing.** A weekly or monthly allowance is divided across the days left before its
  reset. Unused share carries forward; today's share cannot be borrowed from later
  days without the owner agreeing.
- **Value against cost.** Each delegated task carries a value (set by the standing
  rule, or by the owner when asked). Freya compares it with the share of allowance the
  task would use and how much is left until the reset. Low value near a limit: stay
  local or wait. High value: go. The comparison and its inputs are recorded.
- **Value levels.** Low: cloud only when allowance is plentiful for the period,
  otherwise local or wait. Normal: cloud within the day's paced share. High: may
  exceed the day's share, and the owner is told. The level comes from the owner when
  asking, or from the matching standing rule, or is normal. Freya and models never
  raise it.
- **Urgent.** A separate flag the owner sets: the task does not wait for a reset.
  An urgent task may also use more than one cloud route at the same time, either by
  giving independent parts to different providers or by asking two for the same
  answer and comparing. Each route used must be covered by its own approval, each
  draws on its own allowance, and the prompt says that the material goes to more than
  one vendor. Urgent does not widen what may be sent.
- **Order of routes.** Local first when a local model is good enough for that kind of
  task (ESC-001, judged from the evaluation results, not from the model's own
  confidence). Then plan allowance. Paid API calls last.
- **Near a cap.** At a warning level Freya says so. When a task would cross a cap she
  shows what is used, what the task needs, and when the limit resets, and offers: go
  over by a stated amount, wait for the reset, use another route, or stay local. Going
  over applies to that task only. Where a vendor's plan limit is a hard stop, going
  over is not possible and the offer is the other three.
- **Unknown outcomes.** A call that fails without reporting usage is counted at its
  full estimate.
- Every task also has a maximum number of calls and a time limit (ESC-006).

## Keys

API keys are read from Windows Credential Manager at the moment of a call, by the
provider only. They are never written to code, config, the audit log, `data/`, or a
child program's environment. The owner enters them; Freya has no code path that
creates or prints one. Plan routes use the vendor program's own sign-in, which Freya
never reads.

## Open before building

1. **Vendor terms for plan routes.** Whether each vendor allows its program to be
   driven by another application on a subscription has not been checked. Plan routes
   are not built until it has, per vendor.
2. **Figures.** Money caps are zero until the owner sets them. The warning level and
   the per-rule plan limits are the owner's to set.
3. **When parallel use "makes sense".** The test for splitting an urgent task across
   providers, or asking two for the same answer, is not yet defined. (Decided: Freya
   starts with no standing rules; value is low, normal or high, plus urgent.)
4. **Authorization of the confirmation click.** The window has no pairing or per-client
   scope yet, so a click is attributed to the fixed `local-owner`. This is acceptable
   on a loopback-only alpha and must be revisited with the authenticated gateway.
5. **Codex's ledger work** (`feat/synthetic-self-design`) holds reservation and
   accounting ideas that may be reusable for the usage ledger. It has not been reviewed.
6. A second opinion from Codex on this design, as the project rules ask before an
   architecture decision, once its allowance resets.

## Suggested build order

1. Usage ledger and limits, with no cloud provider (tested with a fake route).
2. Material settings and the request description, using the existing source labels.
3. Plan routes, if the terms check in the open items allows.
4. Standing rules, the approval prompt, and the voice confirmation.
5. Pacing and the value comparison.
6. `anthropic-api` and `openai-api` providers behind deny-by-default capabilities,
   with zero caps.
