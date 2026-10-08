"""
A stand-in speech helper for the tests. It uses the real helper loop
but generates a plain tone instead of loading a model.
"""
import os
import sys

sys.path.insert(0, os.environ["FREYA_TEST_WORKERS"])

from worker_base import serve  # noqa: E402

import time  # noqa: E402

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

# Libraries print all sorts of things; none of it may reach Freya.
print('{"ok": true, "noise": "printed by a library"}')


def tone(request):
    seconds = request.get("seconds", 0.5)
    sf.write(request["output"], np.full(int(8000 * seconds), 0.2, "float32"), 8000)

    return {
        "sample_rate": 8000,
        "load_seconds": 0.0,
        "generate_seconds": 0.01,
        "first_audio_seconds": 0.01,
        "gpu_peak_mb": None,
        "device": "cpu",
        "echo": {
            key: value for key, value in request.items() if key != "output"
        },
    }


def fail(request):
    raise ValueError("the model fell over")


def crash(request):
    os._exit(3)


def sleep(request):
    time.sleep(request["seconds"])

    return {}


def empty(request):
    sf.write(request["output"], np.zeros(0, "float32"), 8000)

    return {"sample_rate": 8000}


serve(
    {
        "synthesize": tone,
        "design": tone,
        "fail": fail,
        "crash": crash,
        "sleep": sleep,
        "empty": empty,
        "pid": lambda request: {"pid": os.getpid()},
    }
)
