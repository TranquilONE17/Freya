from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

from freya.core.persistence import ControlStore
from freya.core.usage import USAGE_MIGRATIONS, UsageLedger
from freya.delegation.dispatch import Dispatcher, Route, SentBriefs
from freya.delegation.material import CloudSettings
from freya.delegation.record import ModelRecord
from freya.delegation.screening import Corrections
from freya.providers.model.claude_plan import (
    ANTHROPIC_PLAN_PROVIDER,
    ANTHROPIC_PLAN_VENDOR,
    CLOUD_ANTHROPIC_PLAN_ASK,
    PlanRouteError,
    create_claude_plan_provider,
    register_claude_plan_capability,
)


DATA_DIR = Path(__file__).resolve().parents[3] / "data"


class RouteUnavailable(RuntimeError):
    """
    A route did not answer. `sent` is False only when it is certain
    the brief did not leave this machine.
    """

    def __init__(self, message, sent):
        super().__init__(message)
        self.sent = sent


@dataclass
class CloudDelegation:
    """
    Everything cloud delegation is made of, assembled for one Freya.
    """

    settings: CloudSettings
    ledger: UsageLedger
    corrections: Corrections
    sent: SentBriefs
    record: ModelRecord
    dispatcher: Dispatcher
    usage_store: ControlStore

    def close(self) -> None:
        self.usage_store.close()


def build_cloud_delegation(
    control_plane,
    memories: Callable[[], Iterable[Tuple[str, str]]],
    data_dir=DATA_DIR,
    claude_program=None,
    closeness=None,
) -> CloudDelegation:
    """
    Assemble cloud delegation on a control plane and register the
    Claude plan route on it.

    Assembling it sends nothing and allows nothing. Three things the
    owner controls stay shut until the owner opens them: the
    provider's switch in the cloud settings, a policy rule allowing
    the route's capability (no default seed has one), and a usage
    limit for the route in the ledger (a route with none is refused).

    Every brief then goes dispatcher, broker, route: the dispatcher
    checks and reserves, the broker checks policy and writes the
    audit record, and the route's capability refuses any text the
    dispatcher is not sending at that moment.

    `memories` supplies the (id, text) pairs briefs are screened
    against. The caller decides how they are read.
    """
    data_dir = Path(data_dir)
    settings = CloudSettings(data_dir / "cloud_settings.json")
    usage_store = ControlStore(data_dir / "freya_usage.db", USAGE_MIGRATIONS)
    ledger = UsageLedger(usage_store)
    corrections = Corrections(data_dir / "screening_corrections.json")
    sent = SentBriefs(data_dir / "sent_briefs.jsonl")
    record = ModelRecord(data_dir / "model_record.json")
    broker = control_plane.broker

    # Whether the last failed call may have left the machine. The
    # broker reports a failure as text, so the route notes it here.
    last_failure = {}

    def ask(text):
        last_failure.clear()
        result = broker.invoke(CLOUD_ANTHROPIC_PLAN_ASK, text)

        if result.success:
            return result.result

        if result.outcome in ("denied", "unavailable"):
            # Refused before the route was run.
            sent_anything = False
        else:
            sent_anything = last_failure.get("sent", True)

        raise RouteUnavailable(
            f"Claude could not be asked: {result.error}", sent_anything,
        )

    dispatcher = Dispatcher(
        settings,
        ledger,
        [Route(ANTHROPIC_PLAN_PROVIDER, ANTHROPIC_PLAN_VENDOR, ask)],
        memories,
        sent,
        corrections,
        closeness,
    )

    def note_failure(error: PlanRouteError):
        last_failure["sent"] = error.sent

    control_plane.providers.register(
        create_claude_plan_provider(claude_program)
    )
    control_plane.providers.start(ANTHROPIC_PLAN_PROVIDER)
    control_plane.providers.check_health(ANTHROPIC_PLAN_PROVIDER)
    register_claude_plan_capability(
        control_plane.capabilities,
        dispatcher.in_flight,
        claude_program,
        on_failure=note_failure,
    )

    return CloudDelegation(
        settings=settings,
        ledger=ledger,
        corrections=corrections,
        sent=sent,
        record=record,
        dispatcher=dispatcher,
        usage_store=usage_store,
    )
