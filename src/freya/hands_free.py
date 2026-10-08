import sounddevice as sd

from freya.voice import stt as stt_module
from freya.voice.listener import (
    BackgroundListener,
    UtteranceSegmenter,
    WakeFilter,
)


MUTE_COMMAND = "/mute"
UNMUTE_COMMAND = "/unmute"
NAMES_COMMAND = "/names"
NAME_COMMAND = "/name"

LISTENING_COMMANDS = (
    MUTE_COMMAND,
    UNMUTE_COMMAND,
    NAMES_COMMAND,
    NAME_COMMAND,
)

NAME_USAGE = (
    "Usage: /names, /name add <name>, or /name remove <name>"
)


def load_speech_recognition():
    """
    Load speech recognition, or return None with an explanation when
    it cannot be loaded. Freya still works by typing without it.
    """
    try:
        return stt_module.FreyaSTT()
    except Exception as exc:
        print(
            "Speech recognition could not be loaded, so Freya "
            f"cannot hear you: {exc}"
        )
        return None


def _join_names(names):
    names = [name.title() for name in names]

    if len(names) == 1:
        return names[0]

    return ", ".join(names[:-1]) + " or " + names[-1]


def start_background_listening(
    stt,
    voice,
    gate,
    settings,
    on_request,
):
    """
    Open the microphone in the background and call on_request with
    whatever is said to Freya by name. Returns the listener, or None
    when speech recognition is not available.
    """
    if stt is None:
        return None

    sample_rate = stt_module.MICROPHONE_SAMPLE_RATE
    block_seconds = stt_module.VAD_BLOCK_DURATION
    blocksize = int(sample_rate * block_seconds)

    def open_stream():
        return sd.InputStream(
            device=stt_module.MICROPHONE_DEVICE,
            samplerate=sample_rate,
            channels=stt_module.MICROPHONE_CHANNELS,
            dtype="float32",
            blocksize=blocksize,
        )

    def transcribe(audio):
        return stt.transcribe_audio(
            audio,
            sample_rate,
            hotwords=" ".join(
                name.title() for name in settings.wake_names
            ),
        )

    listener = BackgroundListener(
        open_stream=open_stream,
        blocksize=blocksize,
        segmenter=UtteranceSegmenter(
            block_seconds=block_seconds,
            start_level=stt_module.VAD_START_THRESHOLD,
            stop_level=stt_module.VAD_STOP_THRESHOLD,
            silence_seconds=stt_module.VAD_SILENCE_SECONDS,
        ),
        transcribe=transcribe,
        wake_filter=WakeFilter(lambda: settings.wake_names),
        on_request=on_request,
        is_busy=lambda: gate.busy() or voice.is_busy(),
    )
    listener.start()

    return listener


def describe_listening(listener, settings):
    """
    One line telling the owner whether the microphone is live.
    """
    if listener is None or not listener.running:
        return "Microphone: off. Type to talk to Freya."

    if listener.muted:
        return "Microphone: muted. Use /unmute to turn it back on."

    return (
        "Microphone: listening. Start with "
        f"{_join_names(settings.wake_names)} and she will answer. "
        "Use /mute to turn it off."
    )


def handle_listening_command(user_input, listener, settings):
    """
    Handle /mute, /unmute, /names, and /name. Returns True when the
    input was one of these commands.
    """
    words = user_input.split()

    if not words:
        return False

    command = words[0].lower()

    if command not in LISTENING_COMMANDS:
        return False

    if command in (MUTE_COMMAND, UNMUTE_COMMAND):
        if listener is None or not listener.running:
            print("\nFreya: My microphone is not running.\n")
            return True

        if command == MUTE_COMMAND:
            listener.mute()
        else:
            listener.unmute()

        print(f"\n{describe_listening(listener, settings)}\n")
        return True

    if command == NAMES_COMMAND and len(words) == 1:
        print(
            "\nFreya: I answer to "
            f"{_join_names(settings.wake_names)}.\n"
        )
        return True

    if command == NAME_COMMAND and len(words) >= 3:
        action = words[1].lower()
        name = " ".join(words[2:])

        try:
            if action == "add":
                stored = settings.add_wake_name(name)
                print(
                    f"\nFreya: I'll answer to {stored.title()} "
                    "as well.\n"
                )
                return True

            if action == "remove":
                stored = settings.remove_wake_name(name)
                print(
                    "\nFreya: I'll stop answering to "
                    f"{stored.title()}.\n"
                )
                return True
        except ValueError as exc:
            print(f"\nFreya: {exc}\n")
            return True

    print(f"\n{NAME_USAGE}\n")
    return True
