import json

import pytest

from freya.control_plane import build_local_control_plane
from freya.core import llm
from freya.core.capabilities import CapabilityStatus
from freya.core.model_runtime import (
    ModelRuntimeUnavailable,
    get_model_runtime,
)
from freya.core.providers import ProviderHealth
from freya.providers.model.ollama import (
    OLLAMA_PROVIDER,
    check_ollama_health,
)


@pytest.fixture
def plane(tmp_path, fake_ollama):
    plane = build_local_control_plane(tmp_path / "control.db", None)
    yield plane
    plane.close()


def audit_rows(plane):
    return [
        dict(row)
        for row in plane.store.execute(
            "SELECT * FROM audit_event ORDER BY event_id"
        ).fetchall()
    ]


def test_health_reflects_server_and_installed_models(fake_ollama):
    models = ["gpt-oss:20b", "nomic-embed-text"]

    assert check_ollama_health(models) == ProviderHealth.HEALTHY

    fake_ollama.installed = ["gpt-oss:20b"]
    assert check_ollama_health(models) == ProviderHealth.UNHEALTHY

    fake_ollama.reachable = False
    assert check_ollama_health(models) == ProviderHealth.OFFLINE


def test_runtime_is_unavailable_until_configured():
    with pytest.raises(ModelRuntimeUnavailable):
        get_model_runtime()

    with pytest.raises(ModelRuntimeUnavailable):
        llm.chat([{"role": "user", "content": "hi"}])


def test_chat_goes_through_the_broker_and_is_audited(plane, fake_ollama):
    messages = [{"role": "user", "content": "a private question"}]

    reply = llm.chat(messages)

    rows = audit_rows(plane)

    assert reply == "Hello from the fake model."
    assert fake_ollama.calls == [("chat", "gpt-oss:20b", messages, False, {})]
    assert [(r["kind"], r["capability"]) for r in rows] == [
        ("dispatch", "llm.chat"),
        ("outcome", "llm.chat"),
    ]
    assert rows[1]["outcome"] == "succeeded"
    assert rows[0]["provider"] == OLLAMA_PROVIDER
    assert rows[0]["actor"] == "local-owner"
    # Prompts are never written to the audit log.
    assert "a private question" not in json.dumps(rows)


def test_streamed_chat_yields_chunks_and_records_outcome(plane, fake_ollama):
    chunks = list(llm.chat_stream([{"role": "user", "content": "hi"}]))

    rows = audit_rows(plane)

    assert "".join(chunks).strip() == "Hello from the fake model."
    assert fake_ollama.calls[0][3] is True
    assert [(r["kind"], r["capability"]) for r in rows] == [
        ("dispatch", "llm.chat_stream"),
        ("outcome", "llm.chat_stream"),
    ]
    assert rows[1]["outcome"] == "succeeded"


def test_embedding_goes_through_the_broker(plane, fake_ollama):
    embedding = get_model_runtime().embed("remember this")

    assert embedding == [0.1, 0.2, 0.3]
    assert fake_ollama.calls == [
        ("embed", "nomic-embed-text", "remember this")
    ]
    assert audit_rows(plane)[0]["capability"] == "llm.embed"


def test_json_helpers_use_the_runtime(plane, fake_ollama):
    fake_ollama.reply = '{"relevant_ids": [2], "reason": "It answers it."}'
    candidates = [
        {
            "id": i,
            "type": "fact",
            "key": f"k{i}",
            "similarity": 0.5,
            "content": f"Example fact {i}.",
        }
        for i in (1, 2)
    ]

    result = llm.rerank_memory_candidates("a question", candidates)

    assert result["relevant_ids"] == [2]
    assert fake_ollama.calls[0][4] == {"format": "json"}

    fake_ollama.reply = '{"remember": false}'
    assert llm.evaluate_memory("What is the capital of France?") is None


def test_offline_ollama_is_reported_and_recovers(tmp_path, fake_ollama):
    fake_ollama.reachable = False
    plane = build_local_control_plane(tmp_path / "control.db", None)

    assert any("Ollama is not reachable" in m for m in plane.startup_messages())
    assert plane.capabilities.get_status("llm.chat") == (
        CapabilityStatus.UNAVAILABLE
    )

    with pytest.raises(ModelRuntimeUnavailable) as error:
        llm.chat([{"role": "user", "content": "hi"}])

    assert "not available" in str(error.value)
    assert fake_ollama.calls == []

    # Ollama is started later: the next request re-checks and succeeds.
    fake_ollama.reachable = True

    assert llm.chat([{"role": "user", "content": "hi"}]) == fake_ollama.reply
    assert plane.providers.get(OLLAMA_PROVIDER).health == ProviderHealth.HEALTHY
    plane.close()


def test_missing_model_is_reported(tmp_path, fake_ollama):
    fake_ollama.installed = ["gpt-oss:20b"]
    plane = build_local_control_plane(tmp_path / "control.db", None)

    assert any("model is not installed" in m for m in plane.startup_messages())
    with pytest.raises(ModelRuntimeUnavailable):
        llm.chat([{"role": "user", "content": "hi"}])
    plane.close()


def test_ollama_going_away_marks_provider_offline(plane, fake_ollama):
    assert llm.chat([{"role": "user", "content": "hi"}])

    fake_ollama.reachable = False

    with pytest.raises(ModelRuntimeUnavailable):
        llm.chat([{"role": "user", "content": "hi"}])

    rows = audit_rows(plane)

    assert rows[-1]["outcome"] == "failed-known"
    assert plane.providers.get(OLLAMA_PROVIDER).health == ProviderHealth.OFFLINE
    assert plane.capabilities.get_status("llm.chat") == (
        CapabilityStatus.UNAVAILABLE
    )


def test_stream_failure_mid_reply_is_reported_and_recorded(plane, fake_ollama):
    fake_ollama.fail_mid_stream = True
    received = []

    with pytest.raises(ModelRuntimeUnavailable):
        for chunk in llm.chat_stream([{"role": "user", "content": "hi"}]):
            received.append(chunk)

    rows = audit_rows(plane)

    assert received == ["Hello ", "from "]
    assert rows[-1]["kind"] == "outcome"
    assert rows[-1]["outcome"] == "failed-known"


def test_revoking_policy_stops_model_use(plane, fake_ollama):
    rule = next(
        r for r in plane.policy.list_rules() if r["capability"] == "llm.chat"
    )
    plane.policy.remove_rule(rule["rule_id"])

    with pytest.raises(ModelRuntimeUnavailable) as error:
        llm.chat([{"role": "user", "content": "hi"}])

    assert "Not authorized" in str(error.value)
    assert fake_ollama.calls == []
    assert audit_rows(plane)[-1]["outcome"] == "denied"


def test_warm_models_loads_both_models(plane, fake_ollama):
    plane.warm_models()

    assert [call[:2] for call in fake_ollama.calls] == [
        ("generate", "gpt-oss:20b"),
        ("embed", "nomic-embed-text"),
    ]
    # Warm-up is provider housekeeping, not a capability invocation.
    assert audit_rows(plane) == []

    fake_ollama.reachable = False
    plane.warm_models()
