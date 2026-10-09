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

## How a turn flows

The owner only ever talks to Freya's main local reasoning model. No other model,
local or cloud, answers the owner directly.

1. The owner says something. The main model decides whether she can answer herself or
   whether part of the work should go to another model.
2. For each part she hands over, she writes the prompt: a self-contained brief made
   for that model and that job, as short as it can be while still complete.
3. The router chooses the route for each brief (local first, then plan, then paid API)
   under the limits, check boxes, rules and prompts described below, and sends it.
4. What comes back is untrusted text. It goes to the main model as labelled input, the
   same way tool results do.
5. The main model writes the reply in her own words, saying which models contributed.

This can happen inside an ordinary conversation turn; it does not need the owner to
declare a task. The existing `background` role (memory decisions, ranking, summaries)
stays local always, because it reads the personal store.

The main model always has her full context, including stored memories and past
conversations: she is the intelligence that decides Freya's behaviour, and she uses
what she knows to decide what to hand over and how to brief it (owner decision). What
she must not do is let private information leave the machine. Because she writes
briefs with that context in view, a label check alone cannot stop a memory being
restated in her own words, so every cloud-bound brief passes these guards in order:

1. **Instruction.** She is told to write briefs that stand alone and contain nothing
   about the owner, other people, or this machine beyond what the job needs.
2. **Local screening.** Before a brief is sent, Freya's code compares it with the
   personal store on this machine: names, keys and phrases from saved memories, and
   closeness in meaning using the existing embeddings. This runs locally and sends
   nothing.
3. **Hold on a match.** A brief that matches is not sent. The owner is shown the
   passage and what it matched, and can remove it, send it once anyway, or cancel. A
   standing rule never covers a matched brief.
4. **A local record.** The text of every brief that leaves is kept on this machine for
   the owner to read, with the route and the time. It is personal data and is stored
   and protected like the conversation store, not in the audit log.

This is a strong filter, not a proof. Screening catches copied and closely restated
material; a loose paraphrase or an inference can pass. The owner's prompts, the local
record and the per-provider switches are what bound the remainder.

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
This sorting and the description are built (`freya.delegation`, `CloudSettings`,
`review_brief`) and tested; the window controls and the sending are not.
Before sending, Freya shows a description (which kinds, how much, which route, the
estimated cost) with the full text one click away. Settings are changed by the owner
in the window, never by voice or by a model, and every change is audited. Only the
minimum the task needs is sent (ESC-005).

## Approval

The chat window has a check box per cloud provider for whether it may be used. While
a provider's box is clear, no route to it is used and no approval prompt for it
appears, whatever rules exist; with every box clear, Freya says the work stayed
local. Each starts clear. Only a click in the window changes one, never speech or a
model, and each change is audited.

The setting itself is kept by Freya (an on/off value per provider, in the owner's
settings) and the window changes it with one message type. The check boxes are only
how the page shows it, so they can later become a menu without changing anything
behind the page.

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

Freya keeps a ledger per route: each call's estimated and reported usage, each limit,
how much of it is used, and when it resets. It is built (`freya.core.usage`,
`UsageLedger`) and tested against made-up routes; nothing uses it yet. It has its own
database, `data/freya_usage.db`, so the control database's schema is untouched. It
holds amounts and times only, never prompts or replies.

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
  An urgent task may also use more than one cloud route at the same time. The usual
  way is splitting: independent parts go to different providers. Comparing, where two
  providers answer the same question and Freya shows where they agree and differ, is
  kept for major or complex work. Freya is expected to recognise such a task herself
  (from its size, the number of steps, how much depends on the result, and how local
  attempts went, as ESC-001 asks) and to propose a comparison, saying why. She never
  runs one without the owner's permission. Her recognition is a suggestion only: it
  does not raise the task's value, approve a route, or change what may be sent.
  Each route used must be covered by its own approval, each
  draws on its own allowance, and the prompt says that the material goes to more than
  one vendor. It names each vendor and, under each, describes
  what that vendor would receive: the part of the task, the kinds of material, and
  roughly how much of each, with the full text one click away. For each provider the
  prompt also shows Freya's estimate of how much of
  the remaining allowance for the period the task would use. Urgent does not widen what may be sent.
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

## Where long-term data is kept

Owner decision: the record of sent briefs, and all other long-term data, stays on this
machine, and where each kind lives follows from what the drive is good at. This is
wider than cloud delegation and is its own piece of work; it is recorded here so it is
not lost. This workstation has one NVMe SSD (C:, 2 TB) and one hard disk (D:, 8 TB).

| Drive | Good at | Suited to |
|---|---|---|
| SSD | Fast random reads and writes | Databases and their indexes, anything read during a turn, model files that are loaded often |
| Hard disk | Large capacity, sequential access | Backups, archives, old media and generated images, logs, model files kept but rarely loaded |

Rules for that work: each kind of data declares what it needs (fast lookup or bulk
keeping) and Freya places it by drive type, found from Windows, not by drive letter.
Nothing existing is moved without the owner's say, and the memory database is backed
up before any move. A backup belongs on a different drive from the data it protects.
The same sensitivity rules apply wherever the data lives.

## Vendor terms

Read on 2026-10-09 from the vendors' own pages. This is a reading of published
terms, not legal advice, and both vendors change these pages often: read them again
before each plan route is switched on.

**Anthropic.** The Claude Code legal page says subscription sign-in "is designed to
support ordinary use of Claude Code and other native Anthropic applications", and
that nothing prevents "an end user from signing in to the unmodified Claude Code
binary with their own Claude subscription". Anthropic's support page (update of 7
October 2026) says the Agent SDK and `claude -p` may still be used with subscription
limits and draw from them. What is not permitted: offering Claude sign-in inside
another application, routing requests through plan credentials on behalf of other
users, and collecting or storing Claude credentials or session tokens. Advertised
limits "assume ordinary, individual usage".

**OpenAI.** The Codex documentation presents `codex exec` for scripts and scheduled
jobs, says it "reuses saved CLI authentication by default", and runs it in a
read-only sandbox by default. It recommends API keys for automation and describes
running under a ChatGPT sign-in as an advanced path for "users who need ChatGPT/Codex
rate limits instead of API key usage", on trusted machines. The Terms of Use forbid
extracting output "automatically or programmatically"; no OpenAI page was found that
says how this applies to `codex exec` under a plan, and the Terms page itself could
not be opened during this check. A request for third-party "Sign in with ChatGPT"
was closed as not planned.

What this means for Freya's plan routes:

- She runs the vendor's own unmodified program (`claude -p`, `codex exec`) on this
  PC, as the owner, for the owner's own work. That is the case both vendors describe.
- She never reads, copies, stores or forwards either program's sign-in. The owner
  signs in through the vendor's own flow.
- Plan routes serve the owner only. When Freya has more than one user, each needs
  their own sign-in or an API key; one person's plan never serves another.
- Anthropic's position is stated plainly. OpenAI's is documented practice and not an
  explicit grant, so `openai-plan` carries more risk of a later change or a refusal.

**Included API credits.** Anthropic's Max and Team plans now include monthly API
credits ($100 on Max 5x, $200 on Max 20x; Pro has none), claimed by linking a
Console organization in the plan's billing settings. They cover the Claude API and
the Agent SDK. Usage is never charged to the plan, and with no purchased credits and
auto-reload off, requests stop when the credits run out. So an `anthropic-api` route
can run at no cost beyond the plan: the ledger would hold the credit as a hard
monthly allowance that resets on the billing date, with the money cap still zero.
Claiming the credits and creating the key are owner actions. The owner is on Pro
(2026-10-09), which has no included credits, so `anthropic-api` stays at a zero cap
and unused; this becomes an option only if the plan changes.

## Open before building

1. **Vendor terms for plan routes.** Checked on 2026-10-09; see "Vendor terms" below.
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
