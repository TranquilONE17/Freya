"""Read-only proposal inspection. Never resumes, repairs, deletes or executes work."""
from __future__ import annotations

import argparse
import json
import math
import re
import stat
from pathlib import Path

from coding_proposal_receipt import verify_proposal_receipt
from coding_task_journal import ALLOWED, STATES
from local_coding_agent import BLOCKED_DIRECTORIES

MAX_JOURNAL_BYTES = 256_000
EVENT_FIELDS = {"task_id", "sequence", "state", "timestamp", "details"}
RECEIPT_MARKER = re.compile(r"receipt_sha256=([0-9a-f]{64}); git apply --check passed")
PATCH_MARKER = re.compile(r"sha256=([0-9a-f]{64})")


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate journal field")
        result[key] = value
    return result


def _regular_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError("Unsafe staging artifact")
    return True


def _read_journal(path: Path, task_id: str) -> list[dict]:
    if not _regular_file(path):
        raise ValueError("Journal unavailable")
    with path.open("rb") as file:
        contents = file.read(MAX_JOURNAL_BYTES + 1)
    if len(contents) > MAX_JOURNAL_BYTES:
        raise ValueError("Journal exceeds size limit")
    events = json.loads(contents, object_pairs_hook=_unique_fields)
    if not isinstance(events, list) or not 1 <= len(events) <= 16:
        raise ValueError("Invalid journal history")
    previous = None
    for sequence, event in enumerate(events):
        if (not isinstance(event, dict) or set(event) != EVENT_FIELDS
                or event["task_id"] != task_id
                or type(event["sequence"]) is not int or event["sequence"] != sequence
                or not isinstance(event["state"], str) or event["state"] not in STATES
                or type(event["timestamp"]) not in (int, float)
                or not math.isfinite(event["timestamp"]) or event["timestamp"] < 0
                or not isinstance(event["details"], str) or len(event["details"]) > 2000
                or (sequence == 0 and event["state"] != "requested")
                or (sequence and event["state"] not in ALLOWED[previous])):
            raise ValueError("Invalid journal event")
        previous = event["state"]
    return events


def inspect_proposal(repo: Path, journal_dir: Path, output_dir: Path, task_id: str,
                     expected_receipt_sha256: str | None = None) -> dict:
    """Inspect one explicitly selected task in trusted, quiescent staging roots.

    Caller supplies independently held receipt evidence. Persisted labels/digests
    do not create trust or authority. No directory discovery or writes occur.
    """
    if not isinstance(task_id, str) or not re.fullmatch(r"[a-z0-9-]{1,128}", task_id):
        raise ValueError("Invalid task identity")
    if (expected_receipt_sha256 is not None
            and (not isinstance(expected_receipt_sha256, str)
                 or not re.fullmatch(r"[0-9a-f]{64}", expected_receipt_sha256))):
        raise ValueError("Invalid independently held digest")
    for directory in (repo, journal_dir, output_dir):
        if any(part.lower() in BLOCKED_DIRECTORIES for part in directory.parts):
            raise ValueError("Excluded staging location")
        if directory.is_symlink():
            raise ValueError("Unsafe staging location")
        try:
            attributes = getattr(directory.lstat(), "st_file_attributes", 0)
        except FileNotFoundError:
            attributes = 0
        if attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Unsafe reparse-point location")
    target = repo.resolve()
    journals, artifacts = journal_dir.resolve(), output_dir.resolve()
    if any(root.is_relative_to(target) or target.is_relative_to(root)
           for root in (journals, artifacts)):
        raise ValueError("Staging must be separate from the source target")
    result = {"task_id": task_id, "journal_state": None,
              "classification": "invalid-journal", "reason": "journal-unavailable-or-invalid",
              "authorization_granted": False, "resume_allowed": False}

    def report(classification, reason):
        return {**result, "classification": classification, "reason": reason}

    try:
        events = _read_journal(journals / f"{task_id}.json", task_id)
    except Exception:
        return result  # Never expose persisted contents or exception text.
    state = events[-1]["state"]
    result["journal_state"] = state
    patch_path = artifacts / f"{task_id}.patch"
    receipt_path = artifacts / f"{task_id}.receipt.json"
    try:
        result["patch_present"] = _regular_file(patch_path)
        result["receipt_present"] = _regular_file(receipt_path)
    except (OSError, ValueError):
        return report("invalid-evidence", "unsafe-or-unavailable-staging-artifact")
    if state in ("requested", "generating", "proposed"):
        return report("interrupted", "no-completed-validation-record")
    if state in ("failed", "rejected"):
        return report(state, "terminal-record-no-resume")
    marker = RECEIPT_MARKER.fullmatch(events[-1]["details"])
    if marker is None:
        return report("legacy-unbound", "verified-record-has-no-bound-receipt")
    if not result["patch_present"] or not result["receipt_present"]:
        return report("incomplete", "verified-artifact-missing")
    if expected_receipt_sha256 is None:
        return report("untrusted-evidence", "independently-held-digest-required")
    if marker.group(1) != expected_receipt_sha256:
        return report("untrusted-evidence", "independent-digest-and-journal-disagree")
    try:
        receipt = verify_proposal_receipt(repo, patch_path, receipt_path,
                                          expected_receipt_sha256)
        proposed = PATCH_MARKER.fullmatch(events[-2]["details"])
        if (receipt["task_id"] != task_id or proposed is None
                or proposed.group(1) != receipt["patch_sha256"]):
            return report("invalid-evidence", "task-or-patch-binding-mismatch")
    except Exception:
        return report("stale-or-invalid", "current-evidence-revalidation-failed")
    return report("evidence-current", "selected-content-matches-at-inspection")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--journal-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--expected-receipt-sha256")
    args = parser.parse_args()
    try:
        result = inspect_proposal(args.repo, args.journal_dir, args.output_dir,
                                   args.task_id, args.expected_receipt_sha256)
    except (OSError, ValueError):
        print(json.dumps({"classification": "invalid-input", "authorization_granted": False,
                          "resume_allowed": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
