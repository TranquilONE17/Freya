"""Development-only coordinator for read-only local coding proposals.

No patch application or command execution. Caller must authorize requests before
invocation; this module is NOT a replacement for Freya's Capability Broker.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from coding_task_journal import TaskJournal
from local_coding_agent import ask_ollama, build_prompt, selected_source
from patch_validator import validate_unified_diff
from patch_applicability import check_patch

ENDPOINT = "http://127.0.0.1:11434/api/generate"


def propose(repo: Path, task: str, paths: list[str], model: str,
            journal_dir: Path, output_dir: Path, *,
            generate=ask_ollama) -> dict[str, str]:
    """Record a single local proposal attempt; never apply its result."""
    if not task.strip() or not model.strip() or not paths:
        raise ValueError("Task, model, and selected files are required")
    if len(set(paths)) != len(paths):
        raise ValueError("Duplicate selected paths")
    # Read first, before a task is created; no model receives an unchecked path.
    sources = [(path, selected_source(repo, path)) for path in paths]
    journal = TaskJournal.create(journal_dir)
    output = output_dir.resolve() / f"{journal.task_id}.patch"
    try:
        journal.transition("generating", f"model={model}; files={len(paths)}")
        patch = generate(ENDPOINT, model, build_prompt(task, sources))
        validate_unified_diff(patch, set(paths))
        output_dir.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents accidental overwrite; patch is not executed.
        with output.open("x", encoding="utf-8") as file:
            file.write(patch)
        digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        journal.transition("proposed", f"sha256={digest}")
        check_patch(repo, patch, set(paths))
        journal.transition("verified", "git apply --check passed on disposable copy")
        return {"task_id": journal.task_id, "state": "verified",
                "patch": str(output), "sha256": digest}
    except Exception as exc:
        # Avoid persisting model output or sensitive source text in the journal.
        journal.transition("failed", f"{type(exc).__name__}: proposal failed")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--file", action="append", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--journal-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = propose(args.repo, args.task, args.file, args.model,
                     args.journal_dir, args.output_dir)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
