import builtins

import pytest

from freya.core.model_runtime import ModelRuntimeUnavailable


@pytest.fixture(scope="module")
def main_module():
    # Importing main pulls in the voice and speech libraries, which is slow,
    # so it is done once for this module.
    from freya import main

    return main


def test_main_module_imports(main_module):
    assert callable(main_module.main)


@pytest.mark.parametrize(
    "typed, expected",
    [
        ("\\listen", "/listen"),
        ("\\Conversation", "/Conversation"),
        ("\\talk", "/talk"),
        ("\\image a red fox", "/image a red fox"),
        ("\\voice-file C:\\clips\\a.wav", "/voice-file C:\\clips\\a.wav"),
        ("/listen", "/listen"),
        ("\\o/ hello", "\\o/ hello"),
        ("\\", "\\"),
        ("\\listening is hard", "\\listening is hard"),
        ("what does \\listen do", "what does \\listen do"),
    ],
)
def test_backslash_commands_are_accepted(main_module, typed, expected):
    assert main_module.normalize_command(typed) == expected


def test_unavailable_model_is_reported_instead_of_crashing(
    main_module, monkeypatch, capsys
):
    def unavailable(freya, voice, user_input):
        raise ModelRuntimeUnavailable("The language model is not available.")

    class NoToolRouter:
        def route(self, user_input):
            return None

    monkeypatch.setattr(main_module, "stream_freya_response", unavailable)

    main_module.handle_normal_input(
        freya=None,
        voice=None,
        tool_router=NoToolRouter(),
        image_generator=None,
        gpu_manager=None,
        user_input="hello",
    )

    assert "Freya: The language model is not available." in (
        capsys.readouterr().out
    )
