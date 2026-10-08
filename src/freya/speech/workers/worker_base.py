"""
The loop every speech helper runs.

A helper is a separate program in its own Python environment, started by
Freya with that environment's interpreter. It does not import Freya. It
reads one JSON request per line on standard input and writes one JSON
answer per line back. Audio travels as WAV files at paths Freya chooses,
never through the pipe.
"""
import json
import os
import sys
import time
import traceback


def _protocol_stream():
    """
    Keep the real standard output for answers, and send everything the
    libraries print to standard error (Freya's log) instead, so a stray
    print can never corrupt an answer.
    """
    stream = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr

    return stream


# Done on import, and a helper imports this module before anything
# else, so that libraries which print while loading are covered too.
_ANSWERS = _protocol_stream()


def gpu_peak_megabytes():
    try:
        import torch

        if torch.cuda.is_available():
            return round(torch.cuda.max_memory_allocated() / 1024 / 1024)
    except Exception:
        pass

    return None


def reset_gpu_peak():
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass


def serve(handlers):
    """
    Answer requests until standard input closes. `handlers` maps an
    operation name to a function taking the request and returning a
    dict.
    """
    answers = _ANSWERS

    def answer(message):
        answers.write(json.dumps(message) + "\n")
        answers.flush()

    sys.stdin.reconfigure(encoding="utf-8")
    answer({"ready": True})

    for line in sys.stdin:
        line = line.strip()

        if not line:
            continue

        started = time.perf_counter()

        try:
            request = json.loads(line)
            result = handlers[request["op"]](request) or {}
            answer(
                {
                    "ok": True,
                    "seconds_taken": round(time.perf_counter() - started, 3),
                    **result,
                }
            )
        except Exception as exc:
            traceback.print_exc()
            answer({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
