# Specification: delegation inside a turn

Status: a build specification written 2026-10-10 for the next piece of work. Nothing
in it is built. It applies the owner's decisions in `docs/design/cloud-delegation.md`;
where the two differ, that note wins and this one is wrong. It adopts no requirement or
ADR.

Read first: `docs/design/cloud-delegation.md` (sections "How a turn flows", "What may
leave the machine", "Approval", "Limits and pacing"), the "Composing and sending
briefs" paragraph of `CLAUDE.md`, and these modules, which already exist and are
tested and must not be weakened: `delegation/compose.py`, `delegation/dispatch.py`,
`delegation/screening.py`, `delegation/material.py`, `delegation/service.py`,
`providers/model/claude_plan.py`.

## What this piece does

During an ordinary turn, Freya's main model can hand one piece of work to Claude
through the owner's plan, and use what comes back in its own reply. The owner is asked
whenever the settings require it. With the Claude box clear in the Cloud tab, nothing
changes from today.

Scope of this version: one delegation per turn, to Claude only, of material from the
present turn. Out of scope, and not to be added along the way: delegation to another
local model, more than one provider at once, comparing answers, files and code as
inputs, the value-against-cost weighing, and reading a "limit reached" notice.

## The pieces to build

### 1. A tool the main model can call: `work.delegate`

Register a capability `work.delegate` (provider `delegation-local`, category `cloud`)
with `model_tool: True` and these declared arguments, all text, as `ModelToolHost`
requires:

| Argument | Meaning | Limit |
|---|---|---|
| `kind` | One of `compose.TASK_KINDS` | 20 characters |
| `inputs` | Ids of offered inputs, separated by commas; may be empty | 400 characters |

Do not declare any other argument. In particular there is no argument for a
description, a question, instructions, a reason, a value or an urgency. This is the
rule the whole design rests on: the main model sees the owner's memories, so it is
given no field it could write a sentence in.

The handler builds `{"kind": kind, "inputs": [...]}` and passes it to
`compose.parse_plan` with the inputs offered for this turn (section 2). A refused plan
is returned to the model as a tool error and nothing else happens.

Offer the tool to the model only when delegation can work: at least one provider with
a route is switched on in `CloudSettings`, and a window is connected (section 5). When
it cannot work, do not offer it, so the model does not try.

The capability needs a policy rule. Add a named seed, `alpha-work-delegate`, allowing
it for the local owner. This is a policy change: say so in the pull request, and do not
merge without the owner's agreement. The seed allows the model to *ask* for
delegation. It allows no cloud call; the dispatcher's own locks still decide that.

Tool description for the model (use this text):

> Hands one piece of work to a stronger outside model and returns its answer. Use it
> for work you cannot do well yourself: long analysis, careful reasoning, review. Do
> not use it for conversation, for anything about the user personally, or for what
> you can answer directly. Give the kind of task and the ids of the inputs to send
> with it. You do not write the request; it is written from the inputs you choose.
> The answer comes from another model and may be wrong.

### 2. The inputs offered for a turn

Build the list in Freya's code, once per turn, before the model is first called. Each
entry is a `compose.AvailableInput(input_id, kind, text)`.

| What | Id | Kind |
|---|---|---|
| The owner's present message | `request` | `KIND_REQUEST` |
| Each of the last three exchanges of the live conversation | `turn-1`, `turn-2`, `turn-3` (most recent first), the two messages joined | `KIND_CONVERSATION` |
| Each tool result obtained earlier in this turn | `tool-1`, `tool-2`, ... | `KIND_TOOL_RESULT` |

Labelling rules. These are the part most worth reviewing, because a wrong label is the
one way this wiring could send something it should not.

- The kind comes from where the text came from, decided by code. Never from the
  model, and never by looking at the text.
- Saved memories, conversation summaries, recalled passages and media records are
  **not offered at all** in this version, whatever their setting. Do not add them to
  the list "for later".
- Anything whose origin is not one of the three rows above is not offered.
- The owner's message is offered as typed, not as rewritten by any model.

Tell the model which ids exist by adding one line to the tool hint for the turn, ids
only, for example: `Inputs you may send with delegated work: request, turn-1, turn-2,
tool-1.` Do not put the inputs' text in that line; the model already has the
conversation.

### 3. What the handler does, in order

A `DelegationTurn` object holds the state for one turn: the offered inputs, the turn's
origin (`typed`, `voice` or `window`, already passed to `handle_normal_input` as
`source`), and whether a delegation has already been made this turn.

1. Refuse if a delegation was already made this turn. One per turn.
2. `parse_plan`. Refuse on `PlanRefused`.
3. Choose the provider: in this version, `anthropic` if its switch is on and it has a
   route; otherwise refuse with "no outside model is switched on".
4. `compose_brief(plan, inputs, provider, settings, writer, approved_kinds)`.
   - `writer` is a call to the local model through `ModelRuntime.chat` with role
     `background`, given exactly the messages `compose.writer_messages` returns and
     nothing else. No system prompt of Freya's, no history, no memory.
   - `approved_kinds` starts as what the owner has already approved for this
     conversation (section 4).
5. If the brief is not ready because some kinds are set to ask first, show the
   approval prompt (section 4) and compose again with what was approved. If the owner
   denies, refuse.
6. If the turn's origin is `voice`, show the confirmation prompt even when nothing
   else needs asking. Speech never confirms.
7. `Dispatcher.authorize(brief, route, task_id, value="normal", urgent=False)`. Pass
   exactly those two values. Do not pass `plan.suggested_value` or
   `plan.suggested_urgent`; they are not offered as arguments, so they will be the
   defaults, and they must not reach the ledger in any case.
   - On a screening hold, show the hold prompt (section 4).
   - On a ledger verdict of ask, show the limit prompt (section 4).
   - On wait or refuse, refuse, giving the dispatcher's reason.
8. `Dispatcher.send(authorization, brief.text)`.
9. Return to the model, as the tool result:
   `{"from": "Claude (Anthropic)", "model": ..., "answer": ...}`. It is a tool result
   like any other and is treated as untrusted content. Cut the answer to 8,000
   characters and say so if cut.

Every refusal is returned to the model as a short tool error in plain words, so it
can tell the owner what happened. Never put a brief's text, a screening match, or the
vendor's error detail (`PlanRouteError.detail`) in a tool error, an event on the bus,
a log line or the audit log.

After a turn in which a brief was sent, Freya's reply must say so. Add one sentence to
the tool hint: when you used delegated work, say that part of the answer came from
another model and name it.

### 4. The prompts

All four are shown in the window and answered by a click. Build one mechanism and use
it for all of them.

**Mechanism.** A prompt is a question sent to the connected windows and a single
answer accepted back.

- Send it straight to each connected window's own queue. **Do not publish it on the
  event bus**: the bus keeps a history that is replayed to windows opened later, and a
  prompt can carry a brief's text.
- Give each prompt a random id. Accept an answer only for a pending id, only once,
  and only from a window. The first answer wins; tell the other windows it is closed.
- Wait at most 120 seconds. No answer is a denial.
- New message types: `cloud.prompt` (to the window), `cloud.answer` (from it),
  `cloud.prompt.closed` (to the window). Add them to the gateway deliberately and to
  the list in `CLAUDE.md`.
- If no window is connected, there is nobody to ask: the tool is not offered
  (section 1), and a prompt that finds no window is a denial.
- The handler waits inside a turn, so the turn gate is held while the owner decides.
  That is intended: nothing else should run meanwhile. Shutting down must end the
  wait at once, as a denial.

**What every prompt shows.** The provider's name, then exactly what
`BriefReview.describe()` returns for the brief: kinds and amounts, never the text.
Below it, a control that reveals the full text of the brief as it would be sent. The
text shown must be the same string that is hashed and sent. Take it from the composed
brief; do not rebuild it.

| Prompt | When | Answers |
|---|---|---|
| Approval | Some kinds are set to ask first | Allow once · Allow for this conversation · Deny |
| Confirmation | The turn was spoken | Send · Cancel |
| Hold | Screening matched the personal store | Send once anyway · This is not private · Cancel |
| Limit | The ledger says ask | Go over this once · Cancel |

- *Allow for this conversation* is kept in memory until Freya closes and covers only
  the kinds shown, for that provider.
- *Allow permanently* is in the design but **not in this version**: it needs standing
  rules, which are not built. Do not show the option.
- The hold prompt lists what matched (`ScreeningResult.matches`: the phrase and how it
  matched). If any match is always-private, show no "send anyway" and no "not
  private": only Cancel, with the reason.
- *This is not private* calls `Corrections.mark_not_private` for each matched phrase
  through the existing `cloud.settings.change` capability, so it is audited, then
  screens again.
- "Remove the passage and send" from the design is not in this version.

Everything placed on the page is placed as text, as the rest of the page does.

### 5. Where it is wired

- `delegation/turn.py` (new): `DelegationTurn`, the handler, and the prompt logic.
  It must not import the gateway; it is given a callable `ask_owner(prompt) -> answer`.
- `delegation/service.py`: register `delegation-local` and `work.delegate`, with the
  handler reading the current `DelegationTurn`.
- `core/assistant.py`: at the start of `respond_stream`, build the offered inputs and
  set the current `DelegationTurn`; clear it when the turn ends, including when it
  ends in an error. Tool results gathered during the turn are added to the offered
  inputs as they arrive. Keep the change small; the assistant must still work with no
  delegation service at all, as it does in every existing test.
- `main.py`: pass the turn's `source` through so the turn knows its origin.
- `gateway/server.py`, `gateway/static/app.js` and `index.html`: the prompt mechanism
  and its dialog.
- The window's command path (`window_commands.py`) and the console loop: no change.

The worker model: pass `model="sonnet"` to the Claude route by default, changeable
with `FREYA_CLAUDE_MODEL`. The program's own default is its largest model, which uses
the plan's allowance fastest.

## Tests that must exist and pass

Use the fake Ollama client and the fake Claude program already in the tests. No test
may contact a real model or read the owner's data.

1. With every provider off, the tool is not offered and a turn behaves exactly as
   before.
2. A plan with any extra argument, an unknown kind, or an input id that was not
   offered is refused, and nothing is composed.
3. The brief writer's messages contain only cleared material: a test puts a made-up
   memory in the assistant's context and asserts it appears in neither the writer's
   messages nor the brief.
4. Memories, summaries and recalled passages are never in the offered inputs, even
   with their settings changed to allowed.
5. Ask-first material leads to an approval prompt; deny sends nothing; allow once
   sends once and asks again next turn; allow for this conversation does not ask
   again for those kinds and still asks for others.
6. A spoken turn always gets the confirmation prompt, including when nothing else
   needs asking, and no answer within the time limit sends nothing.
7. A request naming something in a made-up memory is held; "send once" sends; "not
   private" records the correction and then sends; an always-private match offers
   only Cancel.
8. The text shown in a prompt equals the text sent, byte for byte.
9. A prompt is not in the event bus history, and a window opened afterwards is not
   sent it.
10. An answer for an unknown id, a second answer, and an answer after the time limit
    are all ignored.
11. Two delegations in one turn: the second is refused.
12. No brief text, screening match or vendor error detail appears in the audit log,
    the bus history or the console output of any test above.
13. Shutting down while a prompt is waiting ends the turn promptly.
14. The whole existing suite still passes.

## Before it merges

- Run `scripts/codex.ps1 review` against the base branch and deal with what it finds.
- One real run, with the owner present: a made-up request, the Claude box ticked, the
  prompt answered by hand, the brief checked in the Cloud tab's record of what was
  sent.
- Tell the owner about the new policy seed and the new message types.
