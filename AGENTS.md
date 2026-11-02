# Freya — guide for Codex

Read `CLAUDE.md` first. It is the project guide: the architecture documents, the
repository layout, the known state, and the working rules. Everything in it applies
to you as it does to Claude. This file adds only what differs for Codex.

## Rules that matter most

- **Never open, list, print, or copy anything under `data/`.** It holds the owner's
  memories, conversations, voice recordings, and models under terms that forbid
  passing them on. What you read is sent to OpenAI. If a task seems to need a file
  from `data/`, stop and say so instead.
- Never read `.env` files, credentials, or anything under `.venv/`.
- Work on a branch; never commit to `main`. Do not push, open or merge pull
  requests, or change git remotes. The owner merges.
- Do not install software, change system settings, or edit policy rules or shipped
  migrations (see the working rules in `CLAUDE.md`).
- The spec rules in `CLAUDE.md` hold: no ADR is approved, no requirement is
  renumbered, new proposals carry provisional NEW-x labels.

## Working with Claude

Claude Code also works in this repository and may start you with a task or a review.

- Do the task you were given and nothing wider. If you see something else worth
  doing, report it; do not do it.
- When you are given a folder to work in, stay inside it. Claude may be editing
  another checkout of the same repository at the same time.
- End with a short report: what you changed (files), what you ran and its result,
  and what you did not verify. Say plainly when a test failed or was not run.
- In a review, give each finding as file and line, what goes wrong, and the input or
  state that makes it go wrong. Leave out style remarks.

To hand Claude a task or ask it for a review, run it without a window, from the
folder it should work in, with the task on stdin:

    "<task>" | claude -p --permission-mode plan      (read and advise only)
    "<task>" | claude -p --permission-mode acceptEdits   (may edit files there)

Claude needs the network and its own settings folder, which your sandbox blocks, so
ask the owner to approve running that one command outside the sandbox. Never read or
write `~/.claude` yourself. Do not start Claude from a task that Claude gave you.

## Running things

- Tests: `python -m pytest` from the repository root, using `.venv` (Python 3.12).
- Files use LF line endings. Keep the existing code style and comment density.
