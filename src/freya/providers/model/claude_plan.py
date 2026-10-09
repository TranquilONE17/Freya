import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from freya.child_environment import child_environment
from freya.core.capabilities import CapabilityDefinition
from freya.core.providers import ProviderDefinition


ANTHROPIC_PLAN_PROVIDER = "anthropic-plan"
ANTHROPIC_PLAN_VENDOR = "anthropic"
CLOUD_ANTHROPIC_PLAN_ASK = "cloud.anthropic_plan.ask"

# Names the program Freya runs, for a machine where it is not in the
# Claude desktop app's folder.
CLAUDE_PROGRAM_VARIABLE = "FREYA_CLAUDE"

DEFAULT_TIMEOUT_SECONDS = 180
MAX_BRIEF_CHARACTERS = 200_000
MAX_REPLY_CHARACTERS = 200_000

WORKER_INSTRUCTIONS = (
    "You are a worker model. Another AI system has given you one "
    "self-contained brief. Do exactly what the brief asks and reply "
    "with the result only. You have no tools and no files. If the "
    "brief cannot be done from what it contains, say what is missing."
)

# The worker gets no tools, none of the owner's Claude settings,
# memory, plugins or MCP servers, and leaves no session behind.
FIXED_ARGUMENTS = (
    "--print",
    "--output-format", "json",
    "--tools", "",
    "--safe-mode",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--no-session-persistence",
    "--permission-prompts", "none",
    "--system-prompt", WORKER_INSTRUCTIONS,
)


class PlanRouteError(RuntimeError):
    """
    The brief was not answered. The message is safe to show.
    `sent` is False only when it is certain nothing left this machine.
    """

    def __init__(self, message, sent=True):
        super().__init__(message)
        self.sent = sent


@dataclass(frozen=True)
class WorkerReply:
    """
    What a cloud worker sent back. The text is untrusted content: it
    is input for Freya's main model, never an instruction to Freya.
    """

    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    truncated: bool = False
    raw_usage: Dict[str, object] = field(default_factory=dict)

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def find_claude_program(environ=None) -> Optional[List[str]]:
    """
    The Claude Code program as Anthropic published it, or None.

    Freya runs the program itself rather than a launcher script, so
    nothing she passes is ever read by a command interpreter.
    """
    environ = os.environ if environ is None else environ
    named = environ.get(CLAUDE_PROGRAM_VARIABLE)

    if named:
        return [named] if Path(named).is_file() else None

    root = Path(environ.get("APPDATA", "")) / "Claude" / "claude-code"

    try:
        versions = sorted(
            (entry for entry in root.iterdir() if entry.is_dir()),
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return None

    for version in versions:
        for program in version.rglob("claude.exe"):
            return [str(program)]

    return None


def ask_claude_plan(
    brief: str,
    program: Sequence[str],
    *,
    model: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> WorkerReply:
    """
    Send one brief to Claude through the owner's own signed-in Claude
    Code program and return the reply.

    Freya never reads that program's sign-in. The brief goes in on
    standard input, so no part of it becomes a command-line argument.
    The program runs in an empty folder made for this call.
    """
    if not isinstance(brief, str) or not brief.strip():
        raise PlanRouteError("There is no brief to send.", sent=False)
    if len(brief) > MAX_BRIEF_CHARACTERS:
        raise PlanRouteError("The brief is too long to send.", sent=False)

    command = [*program, *FIXED_ARGUMENTS]
    if model:
        command += ["--model", model]

    with tempfile.TemporaryDirectory(prefix="freya-worker-") as folder:
        try:
            completed = subprocess.run(
                command,
                input=brief.encode("utf-8"),
                capture_output=True,
                cwd=folder,
                env=child_environment(),
                timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError as exc:
            raise PlanRouteError(
                "The Claude program could not be started.", sent=False,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise PlanRouteError(
                "Claude did not answer in time. The brief may have been "
                "received.",
            ) from exc

    return _parse_reply(completed)


def _parse_reply(completed) -> WorkerReply:
    output = completed.stdout.decode("utf-8", errors="replace").strip()

    try:
        result = json.loads(output)
    except ValueError:
        result = None

    if not isinstance(result, dict):
        raise PlanRouteError(
            "Claude's program gave an answer Freya could not read "
            f"(exit code {completed.returncode})."
        )

    text = result.get("result")

    if result.get("is_error") or completed.returncode != 0:
        detail = text if isinstance(text, str) and text else "no reason given"
        raise PlanRouteError(f"Claude did not answer: {detail[:300]}")

    if not isinstance(text, str) or not text.strip():
        raise PlanRouteError("Claude returned an empty answer.")

    usage = result.get("usage")
    usage = usage if isinstance(usage, dict) else {}

    return WorkerReply(
        text=text[:MAX_REPLY_CHARACTERS],
        model=_model_name(result),
        input_tokens=_count(usage, "input_tokens")
        + _count(usage, "cache_creation_input_tokens")
        + _count(usage, "cache_read_input_tokens"),
        output_tokens=_count(usage, "output_tokens"),
        truncated=len(text) > MAX_REPLY_CHARACTERS,
        raw_usage=usage,
    )


def _count(usage, name) -> int:
    value = usage.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _model_name(result) -> str:
    models = result.get("modelUsage")
    if isinstance(models, dict) and models:
        return ", ".join(sorted(str(name) for name in models))
    return ""


def create_claude_plan_provider(program=None) -> ProviderDefinition:
    """
    Describe Claude, reached through the owner's subscription, as a
    provider. Healthy means only that the program is present; whether
    the owner is signed in is known when a brief is sent.
    """

    def health():
        return bool(program or find_claude_program())

    return ProviderDefinition(
        provider_id=ANTHROPIC_PLAN_PROVIDER,
        name="Claude through the owner's subscription",
        capabilities=[CLOUD_ANTHROPIC_PLAN_ASK],
        start_handler=lambda: None,
        health_handler=health,
        metadata={
            "vendor": ANTHROPIC_PLAN_VENDOR,
            "leaves_this_machine": True,
        },
    )


def register_claude_plan_capability(registry, program=None, model=None):
    """
    Register the one capability this route offers. It is not offered
    to the model as a tool and is in no default policy seed: only a
    rule the owner adds allows it.
    """

    def ask(brief, timeout=DEFAULT_TIMEOUT_SECONDS):
        resolved = program or find_claude_program()

        if not resolved:
            raise PlanRouteError(
                "The Claude program was not found on this machine.",
                sent=False,
            )

        return ask_claude_plan(brief, resolved, model=model, timeout=timeout)

    registry.register(
        CapabilityDefinition(
            name=CLOUD_ANTHROPIC_PLAN_ASK,
            description=(
                "Sends one brief to Claude through the owner's "
                "subscription and returns the reply. The brief leaves "
                "this machine."
            ),
            provider=ANTHROPIC_PLAN_PROVIDER,
            handler=ask,
            category="cloud",
        )
    )
