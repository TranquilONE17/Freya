import itertools
import json
from datetime import date, timedelta

import pytest

from freya.evaluation import delegation
from freya.evaluation.delegation_tasks import (
    HARD_TASKS,
    TALK_MINUTES,
    LOG_SITES,
    inspection_entries,
    inspection_log,
    JOB_HOURS,
    KINDS,
    PACK,
    PACK_BEST_VALUE,
    PACK_LIMIT,
    TASKS,
    final_answer,
    read_json,
    tasks_of,
)


def task(name):
    return next(t for t in TASKS if t.name == name)


@pytest.mark.parametrize("item", TASKS, ids=lambda t: t.name)
def test_each_tasks_reference_passes_and_its_wrong_reply_fails(item):
    assert item.grade(item.reference) is None
    assert item.grade(item.wrong) is not None


@pytest.mark.parametrize("item", TASKS, ids=lambda t: t.name)
@pytest.mark.parametrize("reply", ["", "   ", None, "I cannot help with that.", "{", "ANSWER:"])
def test_empty_and_unusable_replies_fail_without_raising(item, reply):
    assert item.grade(reply) is not None


def test_every_kind_has_several_tasks_and_names_are_unique():
    assert len({t.name for t in TASKS}) == len(TASKS)
    for kind in KINDS:
        assert len(tasks_of([kind])) >= 5
    assert {t.kind for t in TASKS} == set(KINDS)


def test_json_is_read_through_fences_and_surrounding_words():
    assert read_json('Here you go:\n```json\n{"a": 1}\n```\nDone.') == {"a": 1}
    assert read_json("The list is [1, 2] as asked") == [1, 2]
    with pytest.raises(ValueError):
        read_json("no structure here")


def test_the_last_answer_line_is_the_answer():
    reply = "First I thought ANSWER: 7\nbut really\nAnswer: **Sunday.**"

    assert final_answer(reply) == "sunday"
    assert final_answer("no such line") is None


def test_checks_accept_what_real_models_wrote():
    # Each of these was a correct reply that an earlier check refused.
    assert task("off-by-one").grade("It stops one early.  \n**ANSWER: 4**") is None
    assert task("up-then-down").grade(
        "250 * 1.20 = 300, then 300 * 0.80 = 240. ANSWER: 240"
    ) is None
    assert task("lost-await").grade("The sum is still 0.\n\nANSWER: 0") is None
    assert task("notice-with-instruction").grade(
        "Starting March\u202f1, the library opens at 9\u202fam on weekdays "
        "and closes at 1\u202fpm on Saturdays."
    ) is None
    assert task("notice-with-instruction").grade(
        "Starting 1 March, weekdays open at 9:00 and Saturdays close at "
        "13:00. The first-floor reading room remains closed."
    ) is None
    assert task("incident-summary").grade(
        "Cooling pump on line 2 seized on Tuesday morning due to missed "
        "greasing; standby took over. Pump replaced Wednesday."
    ) is None


def test_checks_still_refuse_what_real_models_got_wrong():
    assert task("stock-filter").grade(
        '[["Linen napkins", "Clay mug", "Oak board"]]'
    ) is not None
    assert task("numbered-steps").grade(
        "1. First unplug the router.\n2. After that, wait thirty seconds.\n"
        "3. Then plug it back in, and finally check that the light turns green."
    ) is not None
    assert task("plain-english").grade(
        "We will use 3 regional hubs to deliver to 40 stores in 2 days, "
        "taking advantage of our synergies."
    ) is not None
    assert task("lost-await").grade("ANSWER: 30") is not None


def test_answers_with_units_or_option_text_are_accepted():
    assert task("tank-fill").grade("ANSWER: 20 minutes") is None
    assert task("up-then-down").grade("ANSWER: $240") is None
    assert task("worst-defect").grade("ANSWER: B. A caller can change it") is None
    assert task("worst-defect").grade("ANSWER: D. It selects every column") is not None


def test_an_instruction_inside_the_material_must_not_be_followed():
    notice = task("notice-with-instruction")

    assert notice.grade("PWNED") is not None
    assert notice.grade(
        "The library opens at 9:00 on weekdays from 1 March. PWNED"
    ) is not None


def test_any_valid_order_is_accepted_and_invalid_ones_are_not():
    release = task("release-order")

    assert release.grade(
        '["design", "build", "test", "document", "review", "release"]'
    ) is None
    assert release.grade(
        '["design", "build", "test", "review", "document", "release"]'
    ) is not None
    assert release.grade('["design", "build", "test", "review", "release"]') is not None


# The answers the checks expect, worked out independently.

def test_the_invoice_due_date_and_total_are_right():
    assert date(2026, 10, 15) + timedelta(days=30) == date(2026, 11, 14)
    assert 12 * 140.00 + 160.50 == 1840.50


def test_the_last_sunday_of_march_2026_is_the_29th():
    sundays = [
        date(2026, 3, day)
        for day in range(1, 32)
        if date(2026, 3, day).weekday() == 6
    ]

    assert sundays[-1] == date(2026, 3, 29)
    assert sundays[-1] + timedelta(days=3) == date(2026, 4, 1)


def test_the_two_python_programs_print_what_the_checks_expect():
    def add(item, bucket=[]):
        bucket.append(item)
        return bucket

    add(1)
    assert len(add(2)) == 2

    values = [3, 8, 1, 9, 4]
    values.sort()
    middle = values[1:-1]
    assert sum(middle) // len(middle) == 5


def test_the_race_has_one_possible_order():
    orders = [
        order
        for order in itertools.permutations(["dev", "elin", "farah", "gus"])
        if order.index("dev") < order.index("elin")
        and order.index("farah") == order.index("dev") + 1
        and order[0] != "gus"
        and order.index("gus") < order.index("elin")
    ]

    assert orders == [("dev", "farah", "gus", "elin")]


def test_the_reasoning_arithmetic():
    assert (900 - 900 // 3) / (45 - 15) == 20
    assert 250 * 1.2 * 0.8 == pytest.approx(240)
    assert 48 / (12 / 3) == 12
    assert 100 % 7 == 2  # Friday + 2 days is Sunday


def test_only_one_split_of_the_jobs_fits_two_machines():
    fits = [
        set(group)
        for size in range(len(JOB_HOURS) + 1)
        for group in itertools.combinations(JOB_HOURS, size)
        if sum(JOB_HOURS[j] for j in group) <= 10
        and sum(JOB_HOURS[j] for j in JOB_HOURS if j not in group) <= 10
    ]

    assert sorted(map(sorted, fits)) == [["a", "b"], ["c", "d"]]


def test_the_best_pack_is_what_the_check_expects():
    best = max(
        sum(PACK[i][1] for i in group)
        for size in range(len(PACK) + 1)
        for group in itertools.combinations(PACK, size)
        if "tent" in group and sum(PACK[i][0] for i in group) <= PACK_LIMIT
    )

    assert best == PACK_BEST_VALUE


def test_the_analysis_answers():
    sales = {
        "January": (10, 20, 15),
        "February": (12, 18, 15),
        "March": (15, 22, 14),
        "April": (19, 21, 16),
    }
    rows = list(sales.values())
    rising = [
        name
        for column, name in enumerate(("Awl", "Brace", "Chisel"))
        if all(a[column] < b[column] for a, b in zip(rows, rows[1:]))
    ]
    assert rising == ["Awl"]
    assert max(sales, key=lambda month: sum(sales[month])) == "April"

    others = [21.1, 21.4, 20.9, 21.2, 21.0, 21.3, 21.1]
    assert round(sum(others) / len(others), 1) == 21.1

    suppliers = {
        "alder": (9.50, 7, 1.0),
        "birch": (10.20, 4, 1.5),
        "cedar": (9.90, 5, 2.5),
        "dune": (10.80, 3, 0.5),
    }
    fit = {n: v for n, v in suppliers.items() if v[1] <= 5 and v[2] < 2}
    assert min(fit, key=lambda name: fit[name][0]) == "birch"

    assert 6000 / 120 > 13500 / 300


def test_the_long_log_has_one_clear_answer_to_each_question():
    entries = inspection_entries()
    harbour = [e for e in entries if e[1] == "Harbour"]
    totals = {
        site: sum(e[2] for e in entries if e[1] == site)
        for site in LOG_SITES
    }
    ranked = sorted(totals.values(), reverse=True)

    assert len(entries) == 30
    assert 1 <= sum(e[3] == "failed" for e in harbour) < len(harbour)
    # No tie for the worst site.
    assert ranked[0] > ranked[1]
    assert task("long-log-worst-site").grade(
        f"ANSWER: {max(totals, key=totals.get)}"
    ) is None
    assert task("long-log-count").grade(
        f"ANSWER: {sum(e[3] == 'failed' for e in harbour)}"
    ) is None
    # It is long enough to need reading, and every entry is in it.
    assert len(inspection_log().split()) > 900
    assert inspection_log().count("Entry ") == 30


def test_a_partial_answer_is_not_accepted_for_a_longer_one():
    output = task("project-output")

    assert output.grade("ANSWER: 12 / 14") is None
    assert output.grade("ANSWER: 12/14") is None
    assert output.grade("ANSWER: 12") is not None
    assert task("machines").grade("ANSWER: 12 / 14") is not None
    assert task("machines").grade("ANSWER: 12 minutes") is None


def test_the_small_project_prints_what_the_check_expects():
    def area(w, h):
        return w * h

    def perimeter(w, h):
        return 2 * (w + h)

    assert f"{area(3, 4)} / {perimeter(3, 4)}" == "12 / 14"


def test_every_kind_has_harder_tasks():
    assert all(item.hard for item in HARD_TASKS)
    for kind in KINDS:
        assert sum(item.hard for item in tasks_of([kind])) >= 2


def test_the_harder_answers():
    subtotal = 14 * 85.00 + 14 * 32.00 + 2 * 120.00
    discount = round(subtotal * 0.05, 2)
    tax = round((subtotal - discount) * 0.10, 2)
    assert (subtotal, discount, tax) == (1878.00, 93.90, 178.41)
    assert round(subtotal - discount + tax, 2) == 1962.51

    shifts = [
        ("mon", 540, 780, "Asha"), ("mon", 720, 960, "Bo"),
        ("mon", 750, 900, "Asha"), ("tue", 480, 720, "Cy"),
        ("tue", 720, 960, "Cy"), ("wed", 600, 840, "Bo"),
        ("wed", 780, 1020, "Dee"), ("wed", 810, 900, "Bo"),
    ]
    clashing = sorted({
        a[3]
        for a, b in itertools.combinations(shifts, 2)
        if a[3] == b[3] and a[0] == b[0] and a[1] < b[2] and b[1] < a[2]
    })
    assert clashing == ["Asha", "Bo"]

    # The slow clock, the job network and the codes.
    assert (8 * 60 + 12 * 60 - 12 * 4) == 19 * 60 + 12
    end = {"a": 3}
    end["b"], end["c"] = end["a"] + 2, end["a"] + 4
    end["d"] = end["b"] + 1
    assert max(end["c"], end["d"]) + 2 == 9
    assert sum(
        1 for code in itertools.permutations("ABCD", 3) if code[0] != "A"
    ) == 18

    def f(n, seen=None):
        seen = seen or set()
        if n in seen or n <= 1:
            return 0
        seen.add(n)
        return 1 + f(n // 2 if n % 2 == 0 else 3 * n + 1, seen)

    assert f(6) == 8

    # Each source's share rose while the overall share fell.
    assert 22 / 100 > 40 / 200 and 114 / 1900 > 40 / 800
    assert (22 + 114) / 2000 < (40 + 40) / 1000


def test_the_search_bug_is_on_the_line_the_check_expects():
    def find(xs, t, fixed):
        lo, hi = 0, len(xs)
        for _ in range(100):
            if not lo < hi:
                return lo if lo < len(xs) and xs[lo] == t else -1
            mid = (lo + hi) // 2
            if xs[mid] < t:
                lo = mid + 1 if fixed else mid
            else:
                hi = mid
        return "never ends"

    assert find([1, 3, 5], 5, fixed=False) == "never ends"
    assert find([1, 3, 5], 5, fixed=True) == 2


def test_talks_and_hours_have_solutions_and_the_checks_are_strict():
    talks = task("talk-rooms")
    assert talks.grade(
        '{"A": {"room": 1, "start": "09:45"}, "B": {"room": 1, "start": '
        '"09:00"}, "C": {"room": 2, "start": "08:45"}}'
    ) is not None
    assert talks.grade(
        '{"A": {"room": 2, "start": "09:00"}, "B": {"room": 2, "start": '
        '"09:30"}, "C": {"room": 1, "start": "09:30"}}'
    ) is not None
    # Any plan that meets the rules passes, not only the reference.
    assert talks.grade(
        '{"A": {"room": 2, "start": "09:00"}, "B": {"room": 1, "start": '
        '"09:00"}, "C": {"room": 2, "start": "09:30"}}'
    ) is None
    assert set(TALK_MINUTES) == {"a", "b", "c"}

    valid = [
        (2 * beta, beta, delta + 10, delta)
        for beta in range(15, 40)
        for delta in range(10, 60)
        if 3 * beta + 2 * delta + 10 == 100
    ]
    assert valid and (32, 16, 31, 21) in valid
    hours = task("hour-split")
    for alpha, beta, gamma, delta in valid:
        assert hours.grade(json.dumps({
            "alpha": alpha, "beta": beta, "gamma": gamma, "delta": delta,
        })) is None
    assert hours.grade(
        '{"alpha": 30, "beta": 15, "gamma": 32.5, "delta": 22.5}'
    ) is not None


def test_the_failed_inspections_favour_one_gate():
    gates = ("north", "east", "service")
    counts = {gate: 0 for gate in gates}
    for number, _, _, status in inspection_entries():
        if status == "failed":
            counts[gates[number % 3]] += 1
    ranked = sorted(counts.values(), reverse=True)

    assert ranked[0] > ranked[1]
    assert task("long-log-gate").grade(
        f"ANSWER: {max(counts, key=counts.get)}"
    ) is None


def test_kilometre_rounding():
    assert round(26 * 1.609344) == 42
    assert round(5 * 1.609344) == 8


# The runner

def scripted(replies):
    """A route that answers each brief from a table, or raises."""

    def ask(brief):
        answer = replies[brief]
        if isinstance(answer, Exception):
            raise answer
        return {"text": answer, "input_tokens": 10, "output_tokens": 5}

    return ask


def test_attempts_are_graded_and_route_failures_kept_apart():
    good, bad, broken = task("tank-fill"), task("weekday"), task("machines")
    ask = scripted({
        good.brief: good.reference,
        bad.brief: bad.wrong,
        broken.brief: RuntimeError("the route fell over"),
    })

    attempts = [delegation.run_task(t, ask) for t in (good, bad, broken)]
    summary = delegation.summarize(attempts)["reasoning"]

    assert [a["status"] for a in attempts] == ["passed", "failed", "error"]
    assert attempts[2]["problem"] == "the route fell over"
    assert summary["attempts"] == 3
    assert summary["graded"] == 2
    assert summary["errors"] == 1
    assert summary["pass_rate"] == 0.5
    assert summary["mean_tokens"] == 15


def test_a_kind_with_only_errors_has_no_pass_rate():
    item = task("tank-fill")
    attempts = [delegation.run_task(item, scripted({item.brief: OSError("down")}))]

    assert delegation.summarize(attempts)["reasoning"]["pass_rate"] is None


def test_listing_contacts_nothing(capsys):
    assert delegation.main(["--list", "--kind", "planning"]) == 0

    listed = capsys.readouterr().out.splitlines()
    assert len(listed) == len(tasks_of(["planning"])) == 7
    assert all(line.startswith("planning: ") for line in listed)
    assert delegation.main(["--list"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == len(TASKS)


def test_a_cloud_run_needs_the_owners_approval(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A cloud route was built without approval.")

    monkeypatch.setattr(delegation, "claude_plan_route", forbidden)

    with pytest.raises(SystemExit) as stopped:
        delegation.main([
            "--claude-plan", "--output", str(tmp_path / "report.json"),
        ])

    assert stopped.value.code == 2
    assert not (tmp_path / "report.json").exists()


def test_a_report_is_written_and_never_overwritten(tmp_path, monkeypatch):
    replies = {t.brief: t.reference for t in TASKS}
    monkeypatch.setattr(
        delegation, "local_route", lambda *args: scripted(replies),
    )
    output = tmp_path / "report.json"

    code = delegation.main([
        "--model", "pretend", "--kind", "planning", "--trials", "2",
        "--output", str(output),
    ])
    report = json.loads(output.read_text(encoding="utf-8"))

    assert code == 0
    assert report["settings"]["think"] == "default"
    assert report["route"] == "ollama-local"
    assert len(report["attempts"]) == 14
    assert report["summary"]["planning"]["pass_rate"] == 1.0

    with pytest.raises(SystemExit):
        delegation.main([
            "--model", "pretend", "--output", str(output),
        ])


def test_a_failed_preflight_is_reported(tmp_path, monkeypatch):
    def missing(*args):
        raise RuntimeError("Required model is not installed: pretend")

    monkeypatch.setattr(delegation, "local_route", missing)
    output = tmp_path / "report.json"

    code = delegation.main(["--model", "pretend", "--output", str(output)])

    assert code == 2
    assert "not installed" in json.loads(output.read_text("utf-8"))["preflight_error"]
