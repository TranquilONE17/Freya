"""Opt-in adapter: register proposal-only local coding with Freya's broker.

No policy grant is seeded. The caller must use broker.invoke(CODING_PROPOSE,...).
Do not expose the development CLI directly as a model tool.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from freya.core.capabilities import CapabilityDefinition
from freya.core.providers import ProviderDefinition

from coding_capability_contract import CODING_PROPOSE
from coding_task_runner import propose

PROVIDER_ID = "development-coding-local-alpha"


def register_coding_proposal(control_plane, *, repo: Path, journal_dir: Path,
                             output_dir: Path, model: str,
                             checkpoint: Callable[[], None] | None = None) -> None:
    """Register an opt-in provider, without granting anyone permission."""
    repo = repo.resolve(strict=True)
    journal_dir = journal_dir.resolve()
    output_dir = output_dir.resolve()
    if journal_dir.is_relative_to(repo) or output_dir.is_relative_to(repo):
        raise ValueError("Task artifacts must be outside the source repository")
    if not model.strip():
        raise ValueError("A local model name is required")

    def handler(task: str, files: list[str]):
        return propose(repo, task, files, model, journal_dir, output_dir,
                       checkpoint=checkpoint) if checkpoint is not None else propose(
                           repo, task, files, model, journal_dir, output_dir)

    control_plane.providers.register(
        ProviderDefinition(
            provider_id=PROVIDER_ID,
            name="Local coding proposal alpha",
            capabilities=[CODING_PROPOSE],
            start_handler=lambda: None,
            health_handler=lambda: True,
        )
    )
    control_plane.providers.start(PROVIDER_ID)
    control_plane.providers.check_health(PROVIDER_ID)
    control_plane.capabilities.register(
        CapabilityDefinition(
            name=CODING_PROPOSE,
            description="Propose local code changes without applying them",
            provider=PROVIDER_ID,
            handler=handler,
            category="development",
            metadata={"alpha": True, "model_tool": False},
        )
    )
