import json
from importlib import resources

import pytest

from freya.control_plane import build_local_control_plane
from freya.delegation.material import ALLOWED, KIND_CODE, KIND_MEMORY, NEVER
from freya.delegation.service import (
    CLOUD_SETTINGS_CHANGE,
    build_cloud_delegation,
)
from freya.gateway.server import STATIC_FILES, content_security_policy


@pytest.fixture
def cloud(tmp_path, fake_ollama):
    plane = build_local_control_plane(tmp_path / "control.db", None)
    delegation = build_cloud_delegation(
        plane, lambda: [], tmp_path / "data",
        [str(tmp_path / "no-such-claude.exe")],
    )
    delegation.plane = plane
    yield delegation
    delegation.close()
    plane.close()


def changes(cloud):
    return [
        dict(row) for row in cloud.plane.store.execute(
            "SELECT * FROM audit_event WHERE capability = ? AND kind = 'outcome'",
            (CLOUD_SETTINGS_CHANGE,),
        )
    ]


def test_the_tab_starts_with_everything_shut(cloud):
    state = cloud.window_request({"action": "state"})["state"]

    assert [(p["name"], p["enabled"], p["available"]) for p in state["providers"]] == [
        ("anthropic", False, True),
        ("openai", False, False),
    ]
    by_kind = {entry["kind"]: entry["setting"] for entry in state["material"]}
    assert by_kind["request"] == ALLOWED
    assert by_kind[KIND_MEMORY] == NEVER
    assert state["bars"] == {"low": 0.70, "normal": 0.85, "high": 0.95}
    assert all(not entries for entries in state["corrections"].values())
    assert state["sent_count"] == 0
    assert changes(cloud) == []


def test_each_change_is_made_and_audited_without_its_content(cloud):
    requests = [
        {"action": "provider", "name": "anthropic", "enabled": True},
        {"action": "material", "kind": KIND_CODE, "setting": ALLOWED},
        {"action": "bars", "bars": {"low": 0.6, "normal": 0.8, "high": 0.9}},
        {"action": "mark", "list": "always-private", "phrase": "Project Heron"},
        {"action": "mark", "list": "not-private", "memory": "12"},
    ]

    for request in requests:
        answer = cloud.window_request(request)
        assert "error" not in answer, answer

    state = answer["state"]
    assert state["providers"][0]["enabled"] is True
    assert cloud.settings.setting_for(KIND_CODE) == ALLOWED
    assert state["bars"] == {"low": 0.6, "normal": 0.8, "high": 0.9}
    assert state["corrections"]["always_private_phrases"] == ["project heron"]
    assert state["corrections"]["not_private_memories"] == ["12"]

    rows = changes(cloud)
    assert len(rows) == len(requests)
    assert all(row["outcome"] == "succeeded" for row in rows)
    assert "heron" not in json.dumps(rows).lower()

    removed = cloud.window_request({
        "action": "unmark", "list": "always_private_phrases",
        "entry": "project heron",
    })
    assert removed["state"]["corrections"]["always_private_phrases"] == []


@pytest.mark.parametrize(
    "request_message",
    [
        {"action": "provider", "name": "somebody-else", "enabled": True},
        {"action": "provider", "name": "anthropic", "enabled": "yes"},
        {"action": "material", "kind": "everything", "setting": ALLOWED},
        {"action": "material", "kind": KIND_MEMORY, "setting": "sometimes"},
        {"action": "bars", "bars": {"low": 0.9, "normal": 0.8, "high": 0.95}},
        {"action": "bars", "bars": "high"},
        {"action": "mark", "list": "somewhere", "phrase": "x"},
        {"action": "mark", "list": "not-private"},
        {"action": "mark", "list": "not-private", "phrase": "x", "memory": 1},
        {"action": "mark", "list": "not-private", "phrase": "y" * 201},
        {"action": "unmark", "list": "no_such_list", "entry": "x"},
        {"action": "send-a-brief", "text": "hello"},
        {"action": None},
        "not a message",
    ],
)
def test_bad_requests_change_nothing_and_say_why(cloud, request_message):
    before = cloud.window_request({"action": "state"})["state"]

    answer = cloud.window_request(request_message)

    assert answer["error"]
    assert answer["state"] == before


def test_a_change_is_refused_when_policy_forbids_it(cloud):
    cloud.plane.policy.add_rule(
        "local-owner", CLOUD_SETTINGS_CHANGE, "deny", "test",
    )

    answer = cloud.window_request(
        {"action": "provider", "name": "anthropic", "enabled": True},
    )

    assert answer["error"]
    assert answer["state"]["providers"][0]["enabled"] is False


def test_the_tab_cannot_send_anything_or_raise_a_usage_limit(cloud):
    for action in ("send", "authorize", "limit", "policy", "ask"):
        assert cloud.window_request({"action": action})["error"]

    assert cloud.sent.entries() == []
    assert cloud.ledger.status("anthropic-plan") == []


def test_the_record_of_sent_briefs_is_shown_newest_first(cloud):
    for number in range(3):
        cloud.sent.record("anthropic", "anthropic-plan", f"brief {number}", "answered")

    answer = cloud.window_request({"action": "sent"})

    assert [entry["text"] for entry in answer["sent"]] == [
        "brief 2", "brief 1", "brief 0",
    ]
    assert answer["state"]["sent_count"] == 3


def test_settings_changes_are_not_offered_to_the_model(cloud):
    capability = cloud.plane.capabilities.get(CLOUD_SETTINGS_CHANGE)

    assert not capability.metadata.get("model_tool")
    assert cloud.plane.policy.decide("local-owner", CLOUD_SETTINGS_CHANGE).allow


def test_the_page_has_the_tab_and_its_script_is_served():
    static = resources.files("freya.gateway") / "static"
    page = (static / "index.html").read_text(encoding="utf-8")
    script = (static / "cloud.js").read_text(encoding="utf-8")

    assert 'data-view="cloud"' in page and 'id="view-cloud"' in page
    assert '<script src="/cloud.js"></script>' in page
    assert STATIC_FILES["/cloud.js"][0] == "cloud.js"
    # Text from Freya, including sent briefs, is only ever placed as text.
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "document.write"):
        assert forbidden not in script
    assert "unsafe-inline" not in content_security_policy()
    for wanted in ("cloud-providers", "cloud-material", "cloud-bars-form",
                   "cloud-mark-form", "cloud-not-private", "cloud-always-private",
                   "cloud-sent"):
        assert f'id="{wanted}"' in page
