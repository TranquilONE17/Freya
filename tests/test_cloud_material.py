import json

import pytest

from freya.delegation import (
    ALLOWED,
    ASK,
    DEFAULT_MATERIAL,
    KIND_CODE,
    KIND_CONVERSATION,
    KIND_FILE,
    KIND_MEMORY,
    KIND_PAST_CONVERSATION,
    KIND_REQUEST,
    KIND_TOOL_RESULT,
    NEVER,
    BriefPart,
    CloudSettings,
    kind_of_source,
    review_brief,
)


VENDOR = "anthropic"


@pytest.fixture
def settings(tmp_path):
    return CloudSettings(tmp_path / "cloud_settings.json")


@pytest.fixture
def enabled(settings):
    settings.set_provider(VENDOR, True)
    return settings


def brief():
    return [
        BriefPart(KIND_REQUEST, "Review this function for mistakes."),
        BriefPart(KIND_CODE, "def add(a, b): return a - b", "file:add.py"),
        BriefPart(KIND_CONVERSATION, "We were talking about the adder."),
        BriefPart(KIND_MEMORY, "A made-up fact about a made-up person.", "memory:1"),
        BriefPart(KIND_PAST_CONVERSATION, "A made-up earlier talk.", "conversation:1"),
    ]


def test_the_starting_settings_are_strict(settings):
    assert settings.material == DEFAULT_MATERIAL
    assert settings.setting_for(KIND_REQUEST) == ALLOWED
    assert settings.setting_for(KIND_MEMORY) == NEVER
    assert settings.setting_for(KIND_PAST_CONVERSATION) == NEVER
    assert {
        settings.setting_for(kind)
        for kind in (KIND_CONVERSATION, KIND_TOOL_RESULT, KIND_FILE, KIND_CODE)
    } == {ASK}
    assert settings.enabled_providers() == []
    assert not settings.provider_enabled(VENDOR)


def test_choices_are_remembered(tmp_path):
    path = tmp_path / "cloud_settings.json"
    first = CloudSettings(path)
    first.set_provider(VENDOR, True)
    first.set_provider("openai", True)
    first.set_provider("openai", False)
    first.set_material(KIND_CODE, ALLOWED)

    second = CloudSettings(path)

    assert second.enabled_providers() == [VENDOR]
    assert second.setting_for(KIND_CODE) == ALLOWED
    assert second.setting_for(KIND_MEMORY) == NEVER


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        json.dumps({"material": "everything", "providers": ["anthropic"]}),
        json.dumps({
            "material": {KIND_MEMORY: "yes", "new-kind": ALLOWED},
            "providers": {VENDOR: "true", "openai": 1},
        }),
    ],
)
def test_a_damaged_file_means_the_strict_defaults(tmp_path, content):
    path = tmp_path / "cloud_settings.json"
    path.write_text(content, encoding="utf-8")

    settings = CloudSettings(path)

    assert settings.material == DEFAULT_MATERIAL
    assert settings.enabled_providers() == []


def test_bad_choices_are_refused(settings):
    with pytest.raises(ValueError):
        settings.set_material("everything", ALLOWED)
    with pytest.raises(ValueError):
        settings.set_material(KIND_MEMORY, "sometimes")
    with pytest.raises(ValueError):
        settings.set_provider("", True)
    with pytest.raises(ValueError):
        settings.set_provider(VENDOR, "yes")


def test_nothing_goes_to_a_provider_that_is_off(settings):
    review = review_brief(brief(), VENDOR, settings, frozenset({KIND_CODE}))

    assert review.send == ()
    assert not review.ready
    assert review.describe() == [
        "anthropic is turned off. Nothing would be sent."
    ]


def test_a_brief_is_sorted_by_the_settings(enabled):
    review = review_brief(brief(), VENDOR, enabled)

    assert [part.kind for part in review.send] == [KIND_REQUEST]
    assert review.ask == (KIND_CONVERSATION, KIND_CODE)
    assert [part.kind for part in review.withheld] == [
        KIND_MEMORY,
        KIND_PAST_CONVERSATION,
    ]
    assert not review.ready


def test_approval_releases_only_what_was_approved(enabled):
    review = review_brief(brief(), VENDOR, enabled, frozenset({KIND_CODE}))

    assert [part.kind for part in review.send] == [KIND_REQUEST, KIND_CODE]
    assert review.ask == (KIND_CONVERSATION,)
    assert not review.ready


def test_approval_cannot_release_what_is_set_never(enabled):
    review = review_brief(
        brief(),
        VENDOR,
        enabled,
        frozenset({KIND_CODE, KIND_CONVERSATION, KIND_MEMORY, KIND_PAST_CONVERSATION}),
    )

    assert review.ready
    assert KIND_MEMORY not in {part.kind for part in review.send}
    assert KIND_PAST_CONVERSATION not in {part.kind for part in review.send}
    assert len(review.withheld) == 2


def test_material_of_no_known_kind_never_leaves(enabled):
    parts = [
        BriefPart(None, "unlabelled"),
        BriefPart("something-new", "also unlabelled"),
    ]

    review = review_brief(
        parts, VENDOR, enabled, frozenset({None, "something-new"}),
    )

    assert review.send == ()
    assert len(review.withheld) == 2


def test_only_the_owner_changing_a_setting_releases_memory(enabled):
    enabled.set_material(KIND_MEMORY, ASK)

    asked = review_brief(brief(), VENDOR, enabled)
    approved = review_brief(brief(), VENDOR, enabled, frozenset({KIND_MEMORY}))

    assert KIND_MEMORY in asked.ask
    assert KIND_MEMORY in {part.kind for part in approved.send}


def test_the_description_gives_amounts_and_never_the_text(enabled):
    review = review_brief(brief(), VENDOR, enabled, frozenset({KIND_CODE}))

    lines = review.describe()
    text = "\n".join(lines)

    assert lines[0] == "To anthropic:"
    assert "  the request: 1 piece, about 5 words" in lines
    assert "  Freya's own code: 1 piece, about 7 words" in lines
    assert (
        "  this conversation: 1 piece, about 6 words (needs your permission)"
        in lines
    )
    assert "stored memories: 1 piece" in lines[-1]
    assert "past conversations: 1 piece" in lines[-1]
    for part in brief():
        assert part.text not in text


def test_context_sources_map_to_kinds_and_unknown_ones_to_none():
    assert kind_of_source("saved-memory") == KIND_MEMORY
    assert kind_of_source("conversation-summary") == KIND_PAST_CONVERSATION
    assert kind_of_source("conversation-passage") == KIND_PAST_CONVERSATION
    assert kind_of_source("media") == KIND_FILE
    assert kind_of_source("a-source-added-later") is None
