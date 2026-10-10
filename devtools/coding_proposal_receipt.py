"""Revision-bound validation evidence, never approval or execution authority.

The expected digest must come from a separately trusted journal/result, not from
the receipt itself. This detects stale bytes; it is not a signature or a sandbox.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from local_coding_agent import MAX_RESPONSE_BYTES, selected_source_bytes
from patch_validator import validate_unified_diff

MAX_RECEIPT_BYTES = 1_000_000
FIELDS = {"version", "task_id", "target", "source_sha256", "patch_sha256",
          "validation", "authorization_granted"}


def digest(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def canonical_receipt(task_id: str, target: str, sources: dict[str, str],
                      patch_sha256: str) -> bytes:
    receipt = {"version": 1, "task_id": task_id, "target": target,
               "source_sha256": sources, "patch_sha256": patch_sha256,
               "validation": "structural-and-git-apply-check",
               "authorization_granted": False}
    contents = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(contents) > MAX_RECEIPT_BYTES:
        raise ValueError("Proposal receipt exceeds size limit")
    return contents


def assert_sources_current(repo: Path, sources: dict[str, str]) -> None:
    for path, expected in sources.items():
        if digest(selected_source_bytes(repo, path)) != expected:
            raise ValueError("Selected source changed since generation began")


def _bounded_read(path: Path, limit: int) -> bytes:
    with path.open("rb") as file:
        contents = file.read(limit + 1)
    if len(contents) > limit:
        raise ValueError("Proposal evidence exceeds size limit")
    return contents


def _is_digest(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def verify_proposal_receipt(repo: Path, patch_path: Path, receipt_path: Path,
                            expected_receipt_sha256: str) -> dict:
    """Check current source/artifact bytes against independently held evidence.

    Does not apply a patch, execute Git/code, authorize an action, or mutate a
    journal. Recheck at every later use; this is a point-in-time observation.
    Evidence paths must be supplied by a trusted staging caller, never a model.
    """
    if not _is_digest(expected_receipt_sha256):
        raise ValueError("An independently held receipt digest is required")
    contents = _bounded_read(receipt_path, MAX_RECEIPT_BYTES)
    if digest(contents) != expected_receipt_sha256:
        raise ValueError("Proposal receipt digest mismatch")
    receipt = json.loads(contents)
    if (not isinstance(receipt, dict) or set(receipt) != FIELDS
            or type(receipt["version"]) is not int or receipt["version"] != 1
            or receipt["authorization_granted"] is not False
            or receipt["validation"] != "structural-and-git-apply-check"
            or not isinstance(receipt["task_id"], str) or not receipt["task_id"]
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in receipt["task_id"])
            or not isinstance(receipt["target"], str)
            or not _is_digest(receipt["patch_sha256"])
            or not isinstance(receipt["source_sha256"], dict)
            or not receipt["source_sha256"]
            or any(not isinstance(path, str) or not _is_digest(value)
                   for path, value in receipt["source_sha256"].items())):
        raise ValueError("Invalid proposal receipt")
    if contents != canonical_receipt(receipt["task_id"], receipt["target"],
                                      receipt["source_sha256"], receipt["patch_sha256"]):
        raise ValueError("Proposal receipt is not canonical")
    if receipt["target"] != str(repo.resolve(strict=True)):
        raise ValueError("Proposal receipt target mismatch")
    patch = _bounded_read(patch_path, MAX_RESPONSE_BYTES)
    if digest(patch) != receipt["patch_sha256"]:
        raise ValueError("Proposal artifact digest mismatch")
    validate_unified_diff(patch.decode("utf-8"), set(receipt["source_sha256"]))
    assert_sources_current(repo, receipt["source_sha256"])
    return receipt
