import sys
import traceback
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
LOG_PATH = DATA_DIR / "freya.log"


def main_window():
    """
    Start Freya with no console window: she is used through her own
    window and by voice.

    A program started this way has nowhere to print, and some
    libraries fail when they try. So before anything else is loaded,
    everything Freya would have printed is pointed at data/freya.log.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    log = open(
        LOG_PATH,
        "w",
        encoding="utf-8",
        buffering=1,
    )
    sys.stdout = log
    sys.stderr = log

    try:
        # Imported here, after the log is in place: loading the voice
        # and speech libraries is where most start-up output comes from.
        from freya.main import main

        main(window_only=True)
    except Exception:
        traceback.print_exc()

        from freya.single_instance import show_message

        show_message(
            "Freya stopped because of an error. "
            f"Details are in {LOG_PATH}."
        )
    finally:
        log.flush()
