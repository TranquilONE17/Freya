# Freya — instructions for Codex and other coding agents

Read `CLAUDE.md` in full before changing anything. Despite the name, it is the project
guide for every agent: architecture documents, repository layout, known state, and the
working rules. This file adds what is specific to agents other than Claude Code, and
how work is shared between agents.

## Hard rules

Claude Code has hooks (`.claude/hooks/freya_guard.py`) that block the mistakes below.
You do not run those hooks, so you must follow these rules yourself:

- Never read, print, copy, edit or delete anything under `data/`, or any `*.db` file.
  `data/freya_memory.db` is the owner's personal memory; `data/freya_control.db` is the
  policy table and audit log.
- Never change an existing entry of `MIGRATIONS` in
  `src/freya/core/persistence/control_store.py`. Append a new entry instead.
- Never hand-edit `uv.lock`. Change `pyproject.toml`, run `uv lock`, commit both.
- Never modify files under `src/freya/gateway/static/vendor/`; they are checksummed.
- Never commit to or push to `main`, and never force-push. Work on a branch, open a PR.
- No secrets, keys or tokens anywhere in code, config, commits or logs.
- Do not run generated or untrusted code with access to Freya's Core storage or
  credentials (ARCH-017).
- Owner actions are not yours: installing system software, enabling Windows features
  (Hyper-V), changing ACLs or service accounts, changing policy rows, adopting spec
  amendments, approving ADRs.

## Spec rules

- `docs/specs/Freya_Foundation_v1.1_baseline.docx` is authoritative. Never renumber a
  requirement or reuse an ID. New proposals use provisional labels (NEW-x, UIA-x).
- Do not describe any ADR as approved, the architecture as frozen, or any acceptance
  test as passed unless the owner has said so.
- `docs/design/unified-intelligence-review.md` is a review, not an adopted design.

## Working

- Python 3.12, `uv sync`, then `python -m pytest` from the repository root. The suite
  must pass before you open or update a PR. CI runs it on Windows
  (`.github/workflows/tests.yml`).
- Keep the existing code style, LF line endings, and absolute imports
  (`from freya.core.llm import ...`).
- Keep the two command paths in step (`main.py` loop and `window_commands.py`) until
  they are merged.
- Add tests with every behaviour change. A refactor must not change behaviour and must
  leave the existing tests passing unmodified, except for import paths.
- Small PRs: one task per PR, named in the PR title (for example `[C-2] ...`).

## Sharing work with Claude

- Tasks delegated to you are in `docs/tasks/codex-delegation.md`. Take them in order
  unless the owner says otherwise. Do not start a task another agent owns.
- `.claude/` belongs to Claude Code's configuration. Do not change it except as a task
  says.
- Cross-review: when you finish a PR, say in its description what you changed, how you
  tested it, and what you are unsure of. Claude reviews Codex PRs and Codex reviews
  Claude PRs; the owner merges.
- If a task conflicts with `CLAUDE.md`, the spec, or another open PR, stop and say so
  in the PR or task instead of guessing.
