import json
from typing import Dict, List, Optional, Sequence

from freya.delegation.record import (
    DEFAULT_BARS,
    VALUE_HIGH,
    VALUE_LOW,
    VALUE_NORMAL,
    Candidate,
    Choice,
    ModelRecord,
    choose,
    entry_id,
    validate_bars,
)
from freya.evaluation.delegation_tasks import KINDS


LOCAL_ROUTE = "ollama-local"

# The owner's order of preference: this machine before any cloud route.
LOCAL_TIER = 0
CLOUD_TIER = 1

VALUES = (VALUE_LOW, VALUE_NORMAL, VALUE_HIGH)

# The thinking setting Freya's own replies are sent with. They name
# none, so the model's default applies; the evaluation records an
# unset setting under this word.
REPLY_THINKING = "default"

# Work that no evaluation task covers, from the limits written down
# with the measurements (docs/design/cloud-delegation.md and
# docs/design/model-benchmarks-2026-10-09.md). Nobody, local or cloud,
# has a figure for these, so Freya must not claim skill at them or
# assume another model has it. Remove a line only when tasks for it
# exist and have been run.
NOT_MEASURED = (
    "writing or changing code (a model's code cannot be graded until "
    "it can be run in isolation)",
    "documents of real length",
    "large bodies of code",
    "images",
    "work that takes many steps or many tool calls",
)

EVIDENCE = (
    "Pass counts on short, synthetic tasks graded by automatic checks, "
    "with the model working as a worker on one brief and no tools. "
    "They rank models; they do not prove a pass rate. Fewer than 15 "
    "attempts counts as unmeasured. Unmeasured means unknown, not bad "
    "and not good. Nothing here comes from what a model says about "
    "itself."
)


def _percent(share: float) -> str:
    return f"{share:.0%}"


def _label(about: dict) -> str:
    """An entry in words: where it runs, which model, how it was set."""
    place = "this machine" if about["route"] == LOCAL_ROUTE else about["route"]
    parts = [place, about["model"] or "the route's own model"]
    think = about["settings"].get("think")

    if think:
        parts.append(f"thinking {think}")

    return ", ".join(parts)


def _recorded(record: ModelRecord, route: str, models=None) -> List[tuple]:
    found = []

    for entry in record.entries():
        about = record.about(entry)

        if about is None or about["route"] != route:
            continue
        if models is not None and about["model"] not in models:
            continue

        found.append((entry, about))

    return found


def candidates(
    record: ModelRecord,
    kind: str,
    local_models: Sequence[str],
    cloud_routes: Sequence[str] = (),
) -> List[Candidate]:
    """
    The entries a task of this kind could be given to: every measured
    setting of the models Freya runs here, and every entry on a cloud
    route the caller says is open. A model or route with no figures at
    all is still a candidate, as an unmeasured one.

    Within this machine the quicker entry is the less costly; on a
    cloud route, the one that used fewer tokens. This checks no usage
    limit and sends nothing: a caller that goes on to send must still
    pass the dispatcher.
    """
    found = []

    def add(entries, tier, measure):
        for entry, _ in entries:
            result = record.result(entry, kind)
            cost = getattr(result, measure, None) if result else None
            found.append(Candidate(entry, tier, float(cost or 0.0)))

    for model in dict.fromkeys(local_models):
        entries = _recorded(record, LOCAL_ROUTE, [model])
        add(entries, LOCAL_TIER, "median_seconds")

        if not entries:
            found.append(
                Candidate(entry_id(LOCAL_ROUTE, model, None), LOCAL_TIER)
            )

    for route in cloud_routes:
        entries = _recorded(record, route)
        add(entries, CLOUD_TIER, "mean_tokens")

        if not entries:
            found.append(Candidate(entry_id(route, None, None), CLOUD_TIER))

    return found


def advise(
    record: ModelRecord,
    kind: str,
    value: str,
    local_models: Sequence[str],
    cloud_routes: Sequence[str] = (),
    bars=None,
    unmeasured_allowed=None,
) -> Choice:
    """
    Where a task of this kind and value should go, by the record
    alone. It is advice: it sends nothing and reserves nothing.
    """
    return choose(
        candidates(record, kind, local_models, cloud_routes),
        kind,
        value,
        record,
        bars,
        unmeasured_allowed,
    )


def _standing(result, bars) -> str:
    """The highest value of work a result is good enough for."""
    if result is None or not result.measured:
        return "unmeasured"

    reached = [value for value in VALUES if result.pass_rate >= bars[value]]

    return reached[-1] if reached else "none"


def _entry_report(record, entry, about, bars, kinds) -> dict:
    measured = {}

    for kind in kinds:
        result = record.result(entry, kind)

        if result is None:
            continue

        measured[kind] = {
            "passed": result.passed,
            "attempts": result.attempts,
            "good_enough_for": _standing(result, bars),
        }

    dates = sorted(
        result.measured_at[:10]
        for result in (record.result(entry, kind) for kind in kinds)
        if result and result.measured_at
    )

    return {
        "what": _label(about),
        "measured_on": dates[-1] if dates else "unknown",
        "kinds": measured,
    }


def _whose(choice: Choice, record: ModelRecord) -> Optional[str]:
    if choice.entry is None:
        return None

    about = record.about(choice.entry)

    if about is None:
        # A candidate with no figures at all is named by its id.
        route, model, _ = json.loads(choice.entry)
        about = {
            "route": route,
            "model": None if model == "default" else model,
            "settings": {},
        }

    return _label(about)


def describe_abilities(
    record: ModelRecord,
    model: str,
    local_models: Sequence[str],
    cloud_routes: Optional[Dict[str, bool]] = None,
    bars=None,
    context_tokens: Optional[int] = None,
    kinds: Sequence[str] = KINDS,
) -> dict:
    """
    What has been measured about the model Freya answers with and the
    models she could hand work to, written for that model to read.

    `cloud_routes` maps each cloud route to whether the owner has
    switched its provider on. A route that is off is still described,
    so Freya can say what is known about it, but no work is advised
    towards it.
    """
    bars = validate_bars(DEFAULT_BARS if bars is None else bars)
    cloud_routes = dict(cloud_routes or {})
    local_models = list(dict.fromkeys([model, *local_models]))
    open_routes = [route for route, on in cloud_routes.items() if on]

    own = _recorded(record, LOCAL_ROUTE, [model])
    report = {
        "how_to_read": EVIDENCE,
        "pass_rate_needed": {value: _percent(bars[value]) for value in VALUES},
        "you": {
            "model": model,
            "runs_on": "this machine",
            "reply_thinking": REPLY_THINKING,
            "measured": [
                _entry_report(record, entry, about, bars, kinds)
                for entry, about in own
            ],
        },
        "other_models": [],
        "where_work_should_go": {},
        "never_measured_for_any_model": list(NOT_MEASURED),
    }

    if context_tokens:
        report["you"]["context_tokens"] = context_tokens

    if not own:
        report["you"]["note"] = (
            "Nothing has been measured for this model. Its ability at "
            "every kind of task is unknown."
        )
    elif not any(
        about["settings"].get("think") == REPLY_THINKING for _, about in own
    ):
        report["you"]["note"] = (
            "These figures are for the thinking settings named. Your own "
            "replies use the model's default setting, which has not been "
            "measured, and they are conversation with tools and memory, "
            "which these tasks are not."
        )

    for other in local_models:
        if other == model:
            continue

        for entry, about in _recorded(record, LOCAL_ROUTE, [other]):
            report["other_models"].append(
                _entry_report(record, entry, about, bars, kinds)
            )

    for route, on in sorted(cloud_routes.items()):
        entries = _recorded(record, route)

        for entry, about in entries:
            described = _entry_report(record, entry, about, bars, kinds)
            described["switched_on"] = on
            report["other_models"].append(described)

        if not entries:
            report["other_models"].append({
                "what": route,
                "switched_on": on,
                "kinds": {},
                "note": (
                    "Never measured. Whether it does any kind of task "
                    "better or worse than you is unknown."
                ),
            })

    for kind in kinds:
        advice = {}

        for value in VALUES:
            choice = advise(
                record, kind, value, local_models, open_routes, bars,
            )
            who = _whose(choice, record)
            advice[value] = (
                f"{who}. {choice.reason}" if who else choice.reason
            )

        report["where_work_should_go"][kind] = advice

    return report
