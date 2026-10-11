import json

import pytest

from freya.control_plane import build_local_control_plane
from freya.delegation.abilities import (
    LOCAL_ROUTE,
    NOT_MEASURED,
    advise,
    candidates,
    describe_abilities,
)
from freya.delegation.record import MEASURED, UNMEASURED, ModelRecord, entry_id
from freya.delegation.service import (
    MODEL_RECORD_READ,
    MODEL_RECORD_SEED,
    build_cloud_delegation,
)
from freya.evaluation.delegation_tasks import TASKS
from freya.evaluation.record_reports import main as record_reports, regrade


OWN = "own-model"
CLOUD = "anthropic-plan"


def report(model, passed, graded=20, kind="extraction", think="off",
           route=LOCAL_ROUTE, seconds=2.0, tokens=300):
    return {
        "route": route,
        "model": model,
        "settings": {"think": think} if route == LOCAL_ROUTE else {},
        "created_at": "2026-10-09T12:00:00+00:00",
        "summary": {
            kind: {
                "attempts": graded, "graded": graded, "passed": passed,
                "errors": 0, "median_seconds": seconds, "mean_tokens": tokens,
            },
        },
    }


@pytest.fixture
def record(tmp_path):
    return ModelRecord(tmp_path / "model_record.json")


def describe(record, cloud=None, **kwargs):
    return describe_abilities(
        record, OWN, [OWN], cloud, kinds=["extraction", "planning"], **kwargs,
    )


def test_her_own_results_are_given_as_counts_with_what_they_are_good_for(record):
    record.add_report(report(OWN, 20, think="medium"))
    record.add_report(report(OWN, 15, think="off"))
    record.add_report(report(OWN, 10, kind="planning", think="off"))

    you = describe(record)["you"]
    by_setting = {entry["what"]: entry["kinds"] for entry in you["measured"]}

    assert by_setting[f"this machine, {OWN}, thinking medium"]["extraction"] == {
        "passed": 20, "attempts": 20, "good_enough_for": "high",
    }
    assert by_setting[f"this machine, {OWN}, thinking off"] == {
        "extraction": {"passed": 15, "attempts": 20, "good_enough_for": "low"},
        "planning": {"passed": 10, "attempts": 20, "good_enough_for": "none"},
    }


def test_too_few_attempts_is_unmeasured_not_a_score(record):
    record.add_report(report(OWN, 5, graded=5))

    kinds = describe(record)["you"]["measured"][0]["kinds"]

    assert kinds["extraction"]["good_enough_for"] == "unmeasured"


def test_a_model_with_no_figures_is_told_its_ability_is_unknown(record):
    described = describe(record)

    assert described["you"]["measured"] == []
    assert "unknown" in described["you"]["note"]
    assert "has not been measured" in (
        described["where_work_should_go"]["extraction"]["low"]
    )


def test_figures_for_another_thinking_setting_are_not_passed_off_as_her_replies(record):
    record.add_report(report(OWN, 20, think="medium"))

    assert "default setting, which has not been measured" in (
        describe(record)["you"]["note"]
    )

    record.add_report(report(OWN, 20, think="default"))

    assert "note" not in describe(record)["you"]


def test_an_unmeasured_cloud_model_is_called_unknown_not_better(record):
    record.add_report(report(OWN, 20))

    other = describe(record, {CLOUD: True})["other_models"]

    assert other == [{
        "what": CLOUD, "switched_on": True, "kinds": {},
        "note": other[0]["note"],
    }]
    assert "better or worse than you is unknown" in other[0]["note"]


def test_work_she_is_measured_good_at_stays_on_this_machine(record):
    record.add_report(report(OWN, 20))
    record.add_report(report("claude", 20, route=CLOUD))

    choice = advise(record, "extraction", "high", [OWN], [CLOUD])

    assert choice.basis == MEASURED
    assert json.loads(choice.entry)[0] == LOCAL_ROUTE


def test_work_she_is_measured_poor_at_goes_to_a_measured_better_model(record):
    record.add_report(report(OWN, 12))
    record.add_report(report("claude", 20, route=CLOUD))

    choice = advise(record, "extraction", "high", [OWN], [CLOUD])

    assert choice.basis == MEASURED
    assert json.loads(choice.entry)[:2] == [CLOUD, "claude"]
    assert "extraction" in describe(record, {CLOUD: True})[
        "where_work_should_go"
    ]["extraction"]["high"]


def test_no_work_is_advised_towards_a_provider_that_is_switched_off(record):
    record.add_report(report(OWN, 12))
    record.add_report(report("claude", 20, route=CLOUD))

    described = describe(record, {CLOUD: False})

    # What is known about it is still shown.
    assert described["other_models"][0]["switched_on"] is False
    assert described["other_models"][0]["kinds"]["extraction"]["passed"] == 20
    assert described["where_work_should_go"]["extraction"]["high"] == (
        "No allowed model reaches 95% on extraction."
    )


def test_high_value_work_is_not_handed_to_an_unmeasured_model_unasked(record):
    record.add_report(report(OWN, 12))

    choice = advise(record, "extraction", "high", [OWN], [CLOUD])
    lower = advise(record, "extraction", "normal", [OWN], [CLOUD])

    assert choice.entry is None
    assert "with your permission" in choice.reason
    assert lower.basis == UNMEASURED
    assert lower.entry == entry_id(CLOUD, None, None)


def test_the_quicker_of_two_settings_that_qualify_is_preferred(record):
    record.add_report(report(OWN, 20, think="medium", seconds=3.0))
    record.add_report(report(OWN, 19, think="off", seconds=0.5))

    choice = advise(record, "extraction", "normal", [OWN])

    assert json.loads(choice.entry)[2] == {"think": "off"}
    assert len(candidates(record, "extraction", [OWN, OWN])) == 2


def test_the_owners_bars_decide_what_counts_as_good_enough(record):
    record.add_report(report(OWN, 18))
    strict = {"low": 0.95, "normal": 0.95, "high": 1.0}

    assert describe(record)["you"]["measured"][0]["kinds"]["extraction"][
        "good_enough_for"
    ] == "normal"
    assert describe(record, bars=strict)["you"]["measured"][0]["kinds"][
        "extraction"
    ]["good_enough_for"] == "none"


def test_work_nobody_has_measured_is_always_listed(record):
    record.add_report(report(OWN, 20))

    listed = describe(record)["never_measured_for_any_model"]

    assert listed == list(NOT_MEASURED)
    assert any("writing or changing code" in line for line in listed)


# The tool Freya's model is offered.

@pytest.fixture
def freya(tmp_path):
    plane = build_local_control_plane(tmp_path / "control.db", None)
    cloud = build_cloud_delegation(plane, lambda: [], tmp_path / "data")
    cloud.local_models = (OWN,)
    yield plane, cloud, tmp_path / "data" / "model_record.json"
    cloud.close()
    plane.store.close()


def test_the_model_can_read_the_record_and_nothing_more(freya):
    plane, cloud, _ = freya
    capability = plane.capabilities.get(MODEL_RECORD_READ)

    assert "model_record_read" in [
        tool["function"]["name"] for tool in plane.model_tools.definitions()
    ]
    assert not capability.destructive
    assert "tool_parameters" not in capability.metadata
    assert plane.policy.decide("local-owner", MODEL_RECORD_READ).allow

    answer = json.loads(plane.model_tools.run("model_record_read", {"x": "y"}))

    assert answer["you"]["model"] == OWN
    assert answer["other_models"][0]["switched_on"] is False


def test_figures_added_while_she_runs_are_seen_at_the_next_reading(freya):
    plane, cloud, path = freya

    assert json.loads(plane.model_tools.run("model_record_read"))["you"]["measured"] == []

    ModelRecord(path).add_report(report(OWN, 20))

    measured = json.loads(plane.model_tools.run("model_record_read"))["you"]["measured"]

    assert measured[0]["kinds"]["extraction"]["passed"] == 20


def test_reading_the_record_is_refused_once_its_rule_is_removed(freya):
    plane, cloud, _ = freya

    for rule in plane.policy.list_rules():
        if rule["capability"] == MODEL_RECORD_READ:
            plane.policy.remove_rule(rule["rule_id"])

    assert "error" in json.loads(plane.model_tools.run("model_record_read"))
    assert MODEL_RECORD_SEED == "alpha-model-record"


# Taking finished reports into the record.

def attempt(task, reply, status="passed", problem=None):
    return {
        "task": task.name, "kind": task.kind, "hard": task.hard,
        "status": status, "problem": problem, "reply": reply,
        "input_tokens": 100, "output_tokens": 50, "elapsed_seconds": 1.0,
    }


def finished(attempts, **more):
    return {
        "route": LOCAL_ROUTE, "model": OWN, "settings": {"think": "off"},
        "created_at": "2026-10-09T12:00:00+00:00", "attempts": attempts,
        **more,
    }


def test_a_stored_pass_that_todays_checks_reject_is_recorded_as_a_failure():
    task = TASKS[0]
    regraded = regrade(finished([
        attempt(task, task.wrong, status="passed"),
        attempt(task, task.reference, status="failed", problem="old check"),
    ]))

    assert [a["status"] for a in regraded["attempts"]] == ["failed", "passed"]
    assert regraded["summary"][task.kind]["passed"] == 1


def test_errors_and_cut_replies_keep_counting_against_the_model():
    task = TASKS[0]
    regraded = regrade(finished([
        {"task": task.name, "kind": task.kind, "status": "error",
         "problem": "timed out", "elapsed_seconds": 180.0},
        attempt(task, task.reference, status="failed",
                problem="The reply was cut short."),
    ]))

    assert [a["status"] for a in regraded["attempts"]] == ["error", "failed"]
    assert regraded["summary"][task.kind]["errors"] == 1


@pytest.mark.parametrize("change", [
    {"attempts": []},
    {"suite": "another-set"},
    {"attempts": [{"task": "no-such-task", "kind": "extraction",
                   "status": "passed", "reply": "x"}]},
])
def test_a_report_todays_checks_do_not_apply_to_is_refused(change):
    task = TASKS[0]

    with pytest.raises(ValueError):
        regrade({**finished([attempt(task, task.reference)]), **change})


def test_reports_are_recorded_from_the_command_line(tmp_path, capsys):
    task = TASKS[0]
    good = tmp_path / "good.json"
    bad = tmp_path / "bad.json"
    good.write_text(json.dumps(finished(
        [attempt(task, task.reference)] * 16
    )), encoding="utf-8")
    bad.write_text("{}", encoding="utf-8")
    path = tmp_path / "record.json"

    assert record_reports([str(good), str(bad), "--record", str(path)]) == 1

    record = ModelRecord(path)
    entry = entry_id(LOCAL_ROUTE, OWN, {"think": "off"})

    assert record.entries() == [entry]
    assert record.result(entry, task.kind).passed == 16
    assert "bad.json: not recorded" in capsys.readouterr().err
