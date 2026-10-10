"""Check patch applicability against a disposable copy of selected source files.

This invokes trusted Git's patch parser, never runs code from the patch, and
never writes to the source repository. Not a general-purpose execution sandbox.
"""
from __future__ import annotations

import subprocess
import hashlib
import tempfile
from pathlib import Path

from local_coding_agent import selected_source_bytes, source_text
from patch_validator import validate_unified_diff


def check_patch(repo: Path, patch: str, selected: set[str], *, timeout: int = 15,
                source_sha256: dict[str, str] | None = None) -> None:
    validate_unified_diff(patch, selected)
    if not selected:
        raise ValueError("No files selected")
    if source_sha256 is not None and set(source_sha256) != selected:
        raise ValueError("Source snapshot does not match selected paths")
    with tempfile.TemporaryDirectory(prefix="freya-patch-check-") as directory:
        root = Path(directory)
        for relative in selected:
            # Source reads enforce containment, exclusions and byte limits.
            contents = selected_source_bytes(repo, relative)
            if (source_sha256 is not None
                    and hashlib.sha256(contents).hexdigest() != source_sha256[relative]):
                raise ValueError("Selected source changed since generation began")
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source_text(contents), encoding="utf-8", newline="")
        patch_file = root / "proposal.patch"
        patch_file.write_text(patch, encoding="utf-8", newline="")
        try:
            result = subprocess.run(
                ["git", "-c", "core.hooksPath=/dev/null", "apply", "--check",
                 "--whitespace=error", str(patch_file)],
                cwd=root, capture_output=True, text=True, timeout=timeout,
                check=False, env={"PATH": __import__("os").environ.get("PATH", "")},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("Git patch validation unavailable") from exc
        if result.returncode:
            raise ValueError("Patch does not apply cleanly to selected source files")
