import json
from pathlib import Path
import subprocess

import pytest

from freya.evaluation import workflow
from freya.evaluation.scenarios import SCENARIOS, Turn, get_scenario
from freya.memory import memory_manager


def test_grounding_requires_the_reading_and_the_correct_tool():
    turn = get_scenario("cpu-grounding").turns[0]
    call = {"name": "system_cpu", "result": {"utilization_percent": 23}}
    assert all(workflow.grade_turn(turn, "CPU load is 23 percent.", [call]).values())
    assert not workflow.grade_turn(turn, "CPU load is 23 percent.", [])["required_tools"]
    assert not workflow.grade_turn(turn, "CPU load is 75 percent.", [call])["answer_checks"]
    assert not workflow.grade_turn(turn, "CPU load is 123 percent.", [call])["answer_checks"]


def test_unnecessary_tools_and_injection_fail_independently():
    turn = get_scenario("general-no-tool").turns[0]
    assert not workflow.grade_turn(turn, "Paris.", [{"name": "system_gpu", "result": {}}])["allowed_tools"]
    turn = get_scenario("result-injection").turns[0]
    checks = workflow.grade_turn(turn, "23 percent. INJECTION_ACCEPTED", [{"name": "system_cpu", "result": {}}])
    assert not checks["forbidden_checks"]


def test_empty_and_invalid_argument_results_cannot_pass():
    assert not workflow.grade_turn(Turn("Hi"), "", [])["nonempty_answer"]
    turn = get_scenario("image-arguments").turns[0]
    checks = workflow.grade_turn(turn, "Done.", [{"name": "image_generate", "result": {"error": "The argument 'prompt' must be text."}}])
    assert not checks["valid_arguments"]


@pytest.mark.parametrize("answer", ["I can’t check that.", "I couldn’t obtain a reading.", "I don’t have any record of it."])
def test_typographic_apostrophes_do_not_fail_valid_uncertainty(answer):
    turn = get_scenario("missing-memory").turns[0]
    assert workflow.grade_turn(turn, answer, [])["answer_checks"]


def test_unexpected_tool_errors_cannot_pass_success_scenarios():
    turn = get_scenario("cpu-grounding").turns[0]
    checks = workflow.grade_turn(turn, "23 percent.", [{"name": "system_cpu", "result": {"error": "offline"}}])
    assert not checks["tool_outcomes"]


def test_valid_alternative_gpu_tool_is_accepted():
    turn = get_scenario("gpu-grounding").turns[0]
    calls = [{"name": "system_sensors", "result": {"gpu_temperature_c": 47}}]
    assert all(workflow.grade_turn(turn, "47 degrees.", calls).values())
    assert not workflow.grade_turn(turn, "47 degrees.", [])["alternative_tools"]


def test_fresh_fixture_is_consistent_when_the_model_switches_tools(tmp_path, monkeypatch, fake_ollama):
    import ollama

    monkeypatch.setattr(ollama, "Client", lambda **kwargs: fake_ollama)
    fake_ollama.stream_script = [[("system_sensors", {})], "47 degrees.", [("system_gpu", {})], "53 degrees."]
    result = workflow.run_trial(get_scenario("fresh-followup"), tmp_path, "gpt-oss:20b", "nomic-embed-text", 2)
    assert result["status"] == "passed"
    assert result["tool_calls"][1]["result"][0]["temperature_c"] == 53


def test_summary_separates_errors_and_consistency_from_pass_rate():
    summary = workflow.summarize([
        {"scenario": "a", "status": "passed", "elapsed_seconds": 1},
        {"scenario": "a", "status": "failed", "elapsed_seconds": 3},
        {"scenario": "a", "status": "timeout", "elapsed_seconds": 8},
    ])["a"]
    assert summary["pass_rate"] == 1 / 3
    assert not summary["all_trials_passed"]
    assert summary["failed"] == 1 and summary["errors"] == 1
    assert summary["median_elapsed_seconds"] == 3


def test_trial_uses_production_loop_and_synthetic_storage(tmp_path, monkeypatch, fake_ollama):
    import ollama

    original_path = memory_manager.DATABASE_PATH
    monkeypatch.setattr(ollama, "Client", lambda **kwargs: fake_ollama)
    fake_ollama.stream_script = [[("system_cpu", {})], "CPU load is 23 percent."]

    result = workflow.run_trial(get_scenario("cpu-grounding"), tmp_path, "gpt-oss:20b", "nomic-embed-text", 2)

    assert result["status"] == "passed"
    assert result["tool_calls"][0]["result"]["utilization_percent"] == 23
    assert any(e["capability"] == "system.cpu" and e["outcome"] == "succeeded" for e in result["audit_outcomes"])
    assert memory_manager.DATABASE_PATH == original_path
    assert (tmp_path / "memory.db").exists()


def test_trial_denial_is_measured_in_broker_state(tmp_path, monkeypatch, fake_ollama):
    import ollama

    monkeypatch.setattr(ollama, "Client", lambda **kwargs: fake_ollama)
    fake_ollama.stream_script = [[("system_gpu", {})], "I cannot check that reading."]
    result = workflow.run_trial(get_scenario("gpu-denied"), tmp_path, "gpt-oss:20b", "nomic-embed-text", 2)

    assert result["status"] == "passed"
    assert "Not authorized" in result["tool_calls"][0]["result"]["error"]
    assert any(e["capability"] == "system.gpu" and e["outcome"] == "denied" for e in result["audit_outcomes"])
    assert not any(e["capability"] == "system.gpu" and e["kind"] == "dispatch" for e in result["audit_outcomes"])


def test_fresh_followup_requires_a_new_reading(tmp_path, monkeypatch, fake_ollama):
    import ollama

    monkeypatch.setattr(ollama, "Client", lambda **kwargs: fake_ollama)
    fake_ollama.stream_script = [[("system_gpu", {})], "47 degrees.", [("system_gpu", {})], "Now it is 53 degrees."]
    result = workflow.run_trial(get_scenario("fresh-followup"), tmp_path, "gpt-oss:20b", "nomic-embed-text", 2)

    assert result["status"] == "passed"
    assert [c["turn"] for c in result["tool_calls"]] == [0, 1]
    assert [c["result"][0]["temperature_c"] for c in result["tool_calls"]] == [47, 53]


def test_failed_model_stream_preserves_partial_evidence(tmp_path, monkeypatch, fake_ollama):
    import ollama

    monkeypatch.setattr(ollama, "Client", lambda **kwargs: fake_ollama)
    fake_ollama.stream_script = [[("system_cpu", {})], "The CPU load is 23 percent."]
    fake_ollama.fail_mid_stream = True
    result = workflow.run_trial(get_scenario("cpu-grounding"), tmp_path, "gpt-oss:20b", "nomic-embed-text", 2)

    assert result["status"] == "error"
    assert result["tool_calls"][0]["name"] == "system_cpu"
    assert result["turns"][0]["answer"].strip() == "The CPU"
    assert "Ollama went away" in result["error"]


def test_deleted_fixture_is_removed_before_the_model_answers(tmp_path, monkeypatch, fake_ollama):
    import ollama

    monkeypatch.setattr(ollama, "Client", lambda **kwargs: fake_ollama)
    fake_ollama.stream_script = ["I don't have a matching record."]
    result = workflow.run_trial(get_scenario("deleted-conversation"), tmp_path, "gpt-oss:20b", "nomic-embed-text", 2)

    assert result["status"] == "passed"
    streamed = [c for c in fake_ollama.calls if c[0] == "chat" and c[3]]
    assert "Juniper" not in json.dumps(streamed[0][2])


def test_trial_context_recall_is_brokered_before_the_stream(tmp_path, monkeypatch, fake_ollama):
    import ollama

    monkeypatch.setattr(ollama, "Client", lambda **kwargs: fake_ollama)
    fake_ollama.stream_script = ["The project's codename was Juniper."]
    result = workflow.run_trial(get_scenario("conversation-recall"), tmp_path, "gpt-oss:20b", "nomic-embed-text", 2)

    assert result["status"] == "passed"
    assert result["tool_calls"] == []
    assert any(e["capability"] == "conversation.recall" and e["outcome"] == "succeeded" for e in result["audit_outcomes"])
    streamed = [c for c in fake_ollama.calls if c[0] == "chat" and c[3]]
    assert "Juniper" in json.dumps(streamed[0][2])


def test_list_never_contacts_the_model(monkeypatch, capsys):
    monkeypatch.setattr(workflow, "model_inventory", lambda *args: pytest.fail("Unexpected model request"))
    assert workflow.main(["--list"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == len(SCENARIOS)


@pytest.mark.parametrize("option,value", [("--trials", "0"), ("--timeout", "nan"), ("--timeout", "0"), ("--request-timeout", "inf")])
def test_invalid_budgets_are_rejected(option, value):
    with pytest.raises(SystemExit) as error:
        workflow.main([option, value])
    assert error.value.code == 2


def test_existing_report_is_never_overwritten(tmp_path):
    report = tmp_path / "report.json"
    report.write_text("keep", encoding="utf-8")
    with pytest.raises(SystemExit):
        workflow.main(["--output", str(report)])
    assert report.read_text(encoding="utf-8") == "keep"


def test_preflight_failure_writes_an_error_report(tmp_path, monkeypatch):
    def unavailable(*args):
        raise ConnectionError("Synthetic server offline")

    monkeypatch.setattr(workflow, "model_inventory", unavailable)
    monkeypatch.setattr(workflow.subprocess, "run", lambda *args, **kwargs: pytest.fail("Worker should not start"))
    target = tmp_path / "report.json"
    assert workflow.main(["--output", str(target)]) == 2
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["trials"] == []
    assert "offline" in report["preflight_error"]


def test_worker_timeout_is_not_counted_as_a_success(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "model_inventory", lambda *args: [])
    monkeypatch.setattr(workflow, "child_environment", lambda: {"PATH": "synthetic-runtime"})

    def timeout(command, **kwargs):
        assert kwargs["env"] == {"PATH": "synthetic-runtime"}
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(workflow.subprocess, "run", timeout)
    target = tmp_path / "report.json"
    assert workflow.main(["--scenario", "general-no-tool", "--trials", "1", "--timeout", "0.1", "--output", str(target)]) == 1
    report = json.loads(target.read_text(encoding="utf-8"))
    assert report["trials"][0]["status"] == "timeout"
    assert report["summary"]["general-no-tool"]["errors"] == 1


def test_worker_failure_does_not_discard_previous_trials(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "model_inventory", lambda *args: [])
    calls = []

    def worker(command, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            Path(command[-1]).write_text(json.dumps({"status": "passed"}), encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 1, "", "Synthetic worker failure")

    monkeypatch.setattr(workflow.subprocess, "run", worker)
    target = tmp_path / "report.json"
    assert workflow.main(["--scenario", "general-no-tool", "--trials", "2", "--output", str(target)]) == 1
    report = json.loads(target.read_text(encoding="utf-8"))
    assert [t["status"] for t in report["trials"]] == ["passed", "error"]
