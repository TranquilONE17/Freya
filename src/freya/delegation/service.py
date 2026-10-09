from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

from freya.core.capabilities import LOCAL_OWNER, CapabilityDefinition
from freya.core.persistence import ControlStore
from freya.core.policy import seed_alpha_policy
from freya.core.providers import ProviderDefinition
from freya.core.usage import USAGE_MIGRATIONS, UsageLedger
from freya.delegation.dispatch import Dispatcher, Route, SentBriefs
from freya.delegation.material import CloudSettings
from freya.delegation.record import ModelRecord
from freya.delegation.screening import Corrections
from freya.delegation.window_requests import (
    apply_cloud_change,
    cloud_window_request,
)
from freya.providers.model.claude_plan import (
    ANTHROPIC_PLAN_PROVIDER,
    ANTHROPIC_PLAN_VENDOR,
    CLOUD_ANTHROPIC_PLAN_ASK,
    PlanRouteError,
    create_claude_plan_provider,
    register_claude_plan_capability,
)


DATA_DIR = Path(__file__).resolve().parents[3] / "data"

CLOUD_SETTINGS_PROVIDER = "cloud-settings-local"
CLOUD_SETTINGS_CHANGE = "cloud.settings.change"
CLOUD_SETTINGS_SEED = "alpha-cloud-settings"


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
    broker: object = None
    available_providers: Tuple[str, ...] = ()

    def window_request(self, message: dict) -> dict:
        """
        Answer the Cloud tab. A change goes through the broker, so
        policy must allow it and the audit log records that it was
        made (never what it was).
        """

        def change(request):
            result = self.broker.invoke(CLOUD_SETTINGS_CHANGE, request)
            if not result.success:
                raise ValueError(
                    result.error or "That change could not be made."
                )

        return cloud_window_request(
            self, message, change, self.available_providers,
        )

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
    audit record, and the route's capability sends only when it can
    take the one permit that an authorized send holds.

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
        dispatcher.take_permit,
        claude_program,
        on_failure=note_failure,
    )

    cloud = CloudDelegation(
        settings=settings,
        ledger=ledger,
        corrections=corrections,
        sent=sent,
        record=record,
        dispatcher=dispatcher,
        usage_store=usage_store,
        broker=broker,
        available_providers=(ANTHROPIC_PLAN_VENDOR,),
    )

    # The owner's own changes to these settings, made in the window.
    # This is the one thing here that a default policy seed allows:
    # it lets the owner change their own choices and have each change
    # recorded. It sends nothing and is not offered to the model.
    control_plane.providers.register(
        ProviderDefinition(
            provider_id=CLOUD_SETTINGS_PROVIDER,
            name="The owner's cloud settings",
            capabilities=[CLOUD_SETTINGS_CHANGE],
            start_handler=lambda: None,
            health_handler=lambda: True,
        )
    )
    control_plane.providers.start(CLOUD_SETTINGS_PROVIDER)
    control_plane.providers.check_health(CLOUD_SETTINGS_PROVIDER)
    control_plane.capabilities.register(
        CapabilityDefinition(
            name=CLOUD_SETTINGS_CHANGE,
            description=(
                "Changes one of the owner's cloud settings: a provider's "
                "switch, what a kind of material may do, a pass-rate "
                "bar, or an entry in the screening lists."
            ),
            provider=CLOUD_SETTINGS_PROVIDER,
            handler=lambda request: apply_cloud_change(cloud, request),
            category="cloud",
        )
    )
    seed_alpha_policy(
        control_plane.policy,
        CLOUD_SETTINGS_SEED,
        LOCAL_OWNER.actor,
        [CLOUD_SETTINGS_CHANGE],
    )

    return cloud
