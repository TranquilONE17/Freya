# Claude task: fix the window review findings

Status: pending implementation. Implement this task when the owner explicitly asks.
This file records the implementation prompt; adding it does not implement any fixes.

## Implementation instructions

Please fix these four issues in TranquilONE17/Freya, identified during a review of
main at commit c2dd3efb2060ea38bab78c01f4b79c04c27da346.

Read CLAUDE.md and any applicable repository instructions first. Check the current
code because branches may have changed since the review. Work on a dedicated
branch and open a PR; do not commit directly to main. Preserve unrelated changes
and do not merge anything. Source line references below refer to the reviewed
commit and may move.

### 1. [P1] Shutdown leaves turns running

Source: src/freya/gateway/server.py:144–148; shutdown cleanup in src/freya/main.py.

Gateway.stop() appends a stop marker but does not wait for its worker. Active and
queued turns can continue while main() shuts down voice and closes the control
database.

Implement orderly shutdown: reject new work, cancel pending turns, and finish or
safely cancel active work before closing its dependencies. Check the background
listener too. Avoid deadlocks and indefinite waits.

Reproduction from the review: block the first say action with a threading.Event,
queue a second say action, then call Gateway.stop(). It returns while the worker
is alive. Release the first action: the second action executes after stop.

### 2. [P2] Memory commands are rejected in the window

Source: src/freya/window_commands.py:124–133.

Commands such as /memories, /forget, and /memory-help never reach
FreyaAssistant's existing memory-command handler.

Restore support for all existing memory commands in both the Chat and Console
tabs. Reuse the existing behavior rather than duplicating memory logic. Preserve
unknown-command errors and keyboard-only restrictions.

Reproduction from the review: run_window_command rejects /memories, /forget 1,
and /memory-help with "I don't know the command" instead of dispatching to the
assistant. Test with scratch data, never the owner's personal memory database.

### 3. [P2] Connecting can lose conversation events

Source: src/freya/gateway/server.py:287–299; src/freya/events.py.

The gateway snapshots history before subscribing to the event bus. Events
published between those steps appear in neither the snapshot nor live delivery.

Implement a synchronized snapshot/subscription handoff with buffering as needed.
Ensure events arrive once and in order, including during reconnects. Do not hold
the event-bus lock while performing socket I/O.

Reproduction from the review: a stand-in socket publishes an assistant_chunk
while the hello payload is sent, then publishes assistant_end after subscription.
The chunk exists in the event-bus history but is absent from both the hello
history and the socket's live messages.

### 4. [P2] Bare exit and quit are sent as chat

Source: src/freya/gateway/static/app.js:196–208.

Typing exit or quit sends an ordinary chat message; only /exit reaches the quit
handler.

Route bare exit and quit through the command path in both composers, matching
case-insensitively after trimming. Preserve the rule that window-only Freya can
quit from the window, while console-mode Freya explains that exit must be typed
in the terminal. Do not treat sentences containing these words as quit commands.

Reproduction from the review: executing the actual frontend submitText function
with exit and quit sends type: "say"; /exit sends type: "command".

## Validation and delivery

Add meaningful regression tests for each issue. For concurrency bugs, use
deterministic synchronization rather than sleep-based timing. Exercise the
frontend routing as well as the backend handlers.

Run the relevant tests and the full suite if feasible. Report exactly what passed
and any checks you could not run. The review confirmed these issues with focused
reproductions and passed Python and JavaScript syntax checks, but did not run the
full test suite because pytest was absent and dependency installation was denied.

Finish with a PR describing the fixes, validation, and any remaining limitations.
Do not alter the owner's personal data, policy rules, or audit records.

After implementation, update this file's status with the implementation PR link
and actual validation results. Do not mark a finding resolved without checking it
against the current code and its regression test.
