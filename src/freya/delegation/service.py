import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional, Tuple

from freya.core.capabilities import LOCAL_OWNER, CapabilityDefinition
from freya.core.persistence import ControlStore
from freya.core.policy import seed_alpha_policy
from freya.core.providers import ProviderDefinition
from freya.core.usage import SCOPE_PERIOD, USAGE_MIGRATIONS, UsageLedger
from freya.delegation.dispatch import Dispatcher, Route, SentBriefs
from freya.delegation.material import CloudSettings
from freya.delegation.record import ModelRecord
from freya.delegation.screening import Corrections
from freya.delegation.compose import TASK_KINDS
from freya.delegation.turn import TurnDelegation
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
from freya.tools.model_tools import MODEL_TOOL, TOOL_PARAMETERS
from freya.tools.system_tools import SYSTEM_TOOLS_PROVIDER


DATA_DIR = Path(__file__).resolve().parents[3] / "data"

CLOUD_SETTINGS_PROVIDER = "cloud-settings-local"
CLOUD_SETTINGS_CHANGE = "cloud.settings.change"
CLOUD_SETTINGS_SEED = "alpha-cloud-settings"

# The tool the main model calls to hand one piece of work to Claude.
DELEGATION_PROVIDER = "delegation-local"
WORK_DELEGATE = "work.delegate"
WORK_DELEGATE_SEED = "alpha-work-delegate"

# The model the Claude route asks for. The program's own default is its
# largest model, which uses a plan's allowance fastest.
CLAUDE_MODEL_VARIABLE = "FREYA_CLAUDE_MODEL"
DEFAULT_CLAUDE_MODEL = "sonnet"

# The reason written on a policy rule that a provider's switch added,
# so that switching it off removes that rule and no other.
SWITCH_REASON = "Switched on by the owner in the Cloud tab."

# The owner's starting figure for a plan's weekly allowance (2026-10-09).
# Vendors publish no exact meter, so this is Freya's own estimate.
DEFAULT_WEEKLY_TOKENS = 500_000
WEEKLY_LIMIT = "week"
WEEK_SECONDS = 7 * 86400
MAX_WEEKLY_TOKENS = 1_000_000_000


@dataclass(frozen=True)
class ProviderRoute:
    """The route a provider's switch opens, and the capability behind it."""

    route_id: str
    capability: str


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
    policy: object = None
    routes: dict = field(default_factory=dict)

    @property
    def available_providers(self) -> Tuple[str, ...]:
        return tuple(sorted(self.routes))

    def _switch_rules(self, capability):
        return [
            rule for rule in self.policy.list_rules()
            if rule["capability"] == capability
            and rule["effect"] == "allow"
            and rule["reason"] == SWITCH_REASON
        ]

    def unlock(self, provider: str, now=None) -> None:
        """
        Make a provider usable, as the owner's switch asks (owner
        decision, 2026-10-09: switching a provider on unlocks it). It
        adds the policy rule for the provider's route and, if the
        route has no usage limit yet, the starting weekly allowance.
        A provider Freya has no route to is left as it is.
        """
        route = self.routes.get(provider)

        if route is None:
            return

        if not self._switch_rules(route.capability):
            self.policy.add_rule(
                LOCAL_OWNER.actor, route.capability, "allow", SWITCH_REASON,
            )

        if self.weekly_limit(provider, now) is None:
            self.set_weekly_limit(provider, DEFAULT_WEEKLY_TOKENS, now)

    def lock(self, provider: str) -> None:
        """
        Take away what the switch gave. A rule the owner added by hand
        is not the switch's to remove; the switch being off still
        stops every brief.
        """
        route = self.routes.get(provider)

        if route is None:
            return

        for rule in self._switch_rules(route.capability):
            self.policy.remove_rule(rule["rule_id"])

    def weekly_limit(self, provider: str, now=None):
        route = self.routes.get(provider)

        if route is None:
            return None

        for status in self.ledger.status(route.route_id, now=now):
            if status.name == WEEKLY_LIMIT:
                return status

        return None

    def set_weekly_limit(self, provider: str, tokens, now=None) -> None:
        route = self.routes.get(provider)

        if route is None:
            raise ValueError("Freya has no route to that provider yet.")
        if (
            isinstance(tokens, bool)
            or not isinstance(tokens, int)
            or not 0 <= tokens <= MAX_WEEKLY_TOKENS
        ):
            raise ValueError("A weekly allowance is a whole number of tokens.")

        moment = now or datetime.now(timezone.utc)
        present = self.weekly_limit(provider, moment)
        # The week keeps its dates when only the figure changes.
        resets_at = present.resets_at if present else moment + timedelta(
            seconds=WEEK_SECONDS
        )

        self.ledger.set_limit(
            route.route_id,
            WEEKLY_LIMIT,
            SCOPE_PERIOD,
            "tokens",
            tokens,
            period_seconds=WEEK_SECONDS,
            resets_at=resets_at,
            hard=True,
            source="estimate",
            now=moment,
        )

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

        return cloud_window_request(self, message, change)

    def close(self) -> None:
        self.usage_store.close()


def build_cloud_delegation(
    control_plane,
    memories: Callable[[], Iterable[Tuple[str, str]]],
    data_dir=DATA_DIR,
    claude_program=None,
    closeness=None,
    claude_model=None,
) -> CloudDelegation:
    """
    Assemble cloud delegation on a control plane and register the
    Claude plan route on it.

    Assembling it sends nothing and allows nothing. Three things
    stay shut: the provider's switch in the cloud settings, a policy
    rule allowing the route's capability (no default seed has one),
    and a usage limit for the route in the ledger (a route with none
    is refused). Each stops a brief by itself. The owner opens all
    three at once by switching the provider on in the Cloud tab, and
    closes them by switching it off.

    Every brief then goes dispatcher, broker, route: the dispatcher
    checks and reserves, the broker checks policy and writes the
    audit record, and the route's capability sends only when it can
    take the one permit that an authorized send holds.

    `memories` supplies the (id, text) pairs briefs are screened
    against. The caller decides how they are read. `claude_model` names
    the model the Claude route asks for; without it the route uses
    `FREYA_CLAUDE_MODEL`, or "sonnet".
    """
    data_dir = Path(data_dir)
    claude_model = (
        claude_model
        or os.environ.get(CLAUDE_MODEL_VARIABLE, "").strip()
        or DEFAULT_CLAUDE_MODEL
    )
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
        model=claude_model,
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
        policy=control_plane.policy,
        routes={
            ANTHROPIC_PLAN_VENDOR: ProviderRoute(
                ANTHROPIC_PLAN_PROVIDER, CLOUD_ANTHROPIC_PLAN_ASK,
            ),
        },
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


def build_turn_delegation(
    control_plane,
    cloud: CloudDelegation,
    ask_owner: Callable[[dict], Optional[str]],
    window_connected: Callable[[], bool],
) -> TurnDelegation:
    """
    Let the main model hand one piece of work to Claude during a turn.

    This registers the `work.delegate` tool and offers it to the model
    only while it can work: a provider with a route is switched on in
    the cloud settings and a window is connected to ask the owner in.
    Its policy seed allows the model to *ask* for delegation. It
    allows no cloud call: the dispatcher's own locks (the provider's
    switch, the route's policy rule and its usage limit) still decide
    that, and every question the settings require is put to the owner.

    `ask_owner(prompt)` shows a question in the window and returns the
    id of the answer chosen, or None.
    """
    broker = control_plane.broker
    capabilities = control_plane.capabilities

    def accepts_tool_result(tool_name) -> bool:
        # Only tools that read this PC. A tool that returns saved
        # memories, past conversations or media records must never
        # have its output offered under the label "tool result".
        for capability in capabilities.list_capabilities():
            if capability.name.replace(".", "_") == tool_name:
                return capability.provider == SYSTEM_TOOLS_PROVIDER

        return False

    def mark_not_private(phrase: str) -> bool:
        result = broker.invoke(
            CLOUD_SETTINGS_CHANGE,
            {"action": "mark", "list": "not-private", "phrase": phrase},
        )

        return result.success

    delegation = TurnDelegation(
        cloud,
        control_plane.model_runtime.chat,
        ask_owner,
        window_connected,
        mark_not_private,
        accepts_tool_result,
    )

    control_plane.providers.register(
        ProviderDefinition(
            provider_id=DELEGATION_PROVIDER,
            name="Handing work to an outside model",
            capabilities=[WORK_DELEGATE],
            start_handler=lambda: None,
            health_handler=lambda: True,
        )
    )
    control_plane.providers.start(DELEGATION_PROVIDER)
    control_plane.providers.check_health(DELEGATION_PROVIDER)

    capabilities.register(
        CapabilityDefinition(
            name=WORK_DELEGATE,
            description=(
                "Hands one piece of work to a stronger outside model and "
                "returns its answer. Use it for work you cannot do well "
                "yourself: long analysis, careful reasoning, review. Do "
                "not use it for conversation, for anything about the user "
                "personally, or for what you can answer directly. Give "
                "the kind of task and the ids of the inputs to send with "
                "it. You do not write the request; it is written from the "
                "inputs you choose. The answer comes from another model "
                "and may be wrong."
            ),
            provider=DELEGATION_PROVIDER,
            handler=delegation.delegate,
            category="cloud",
            metadata={
                MODEL_TOOL: True,
                # No argument is a place to write a sentence: only a
                # kind from a fixed list and the ids of offered inputs.
                TOOL_PARAMETERS: {
                    "kind": {
                        "description": (
                            "The kind of task, one of: "
                            + ", ".join(TASK_KINDS)
                            + "."
                        ),
                        "max_length": 20,
                    },
                    "inputs": {
                        "description": (
                            "The ids of the offered inputs to send with "
                            "the work, separated by commas. May be empty."
                        ),
                        "max_length": 400,
                        "optional": True,
                    },
                },
            },
        )
    )

    control_plane.model_tools.add_offer_condition(
        WORK_DELEGATE, delegation.available,
    )
    control_plane.model_tools.add_hint_source(delegation.hint)

    seed_alpha_policy(
        control_plane.policy,
        WORK_DELEGATE_SEED,
        LOCAL_OWNER.actor,
        [WORK_DELEGATE],
    )

    return delegation
