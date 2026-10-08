"""
Qwen3-TTS helper. Runs in Qwen3-TTS's own environment.

Two kinds of model are used, one loaded at a time: VoiceDesign turns a
written description into a short sample of a new voice, and Base speaks
any text in the voice of a reference recording (an uploaded one, or a
sample VoiceDesign made).
"""
# worker_base comes first: importing it moves library chatter off the
# pipe that carries answers to Freya.
from worker_base import gpu_peak_megabytes, reset_gpu_peak, serve

import time

import soundfile as sf
import torch


DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"

MODELS = {
    "design": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "1.7b": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "0.6b": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
}

_loaded = {"name": None, "model": None}
_prompts = {}


def _load(name):
    if _loaded["name"] == name:
        return _loaded["model"], 0.0

    _loaded["name"] = None
    _loaded["model"] = None
    _prompts.clear()

    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    from huggingface_hub import snapshot_download
    from qwen_tts import Qwen3TTSModel

    started = time.perf_counter()
    # Loading from the folder already on disk, not by name: given a
    # name, the tokenizer loader asks the model hub about it even when
    # the files are here, and Freya runs these helpers offline.
    model = Qwen3TTSModel.from_pretrained(
        snapshot_download(MODELS[name], local_files_only=True),
        device_map=DEVICE,
        dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
    )

    _loaded["name"] = name
    _loaded["model"] = model

    return model, time.perf_counter() - started


def _finish(request, audio, rate, load_seconds, generate_seconds):
    sf.write(request["output"], audio, rate)

    return {
        "sample_rate": rate,
        "load_seconds": round(load_seconds, 3),
        "generate_seconds": round(generate_seconds, 3),
        # The whole clip is returned at once.
        "first_audio_seconds": round(generate_seconds, 3),
        "gpu_peak_mb": gpu_peak_megabytes(),
        "device": DEVICE,
    }


def design(request):
    settings = request["settings"]
    model, load_seconds = _load("design")
    reset_gpu_peak()

    started = time.perf_counter()
    audio, rate = model.generate_voice_design(
        text=request["text"],
        language=settings["language"],
        instruct=settings["description"],
    )

    return _finish(
        request, audio[0], rate, load_seconds, time.perf_counter() - started
    )


def synthesize(request):
    settings = request["settings"]
    model, load_seconds = _load(settings["model"])
    reset_gpu_peak()

    started = time.perf_counter()
    transcript = request.get("reference_text") or None
    key = (request["reference"], transcript)

    if key not in _prompts:
        _prompts.clear()
        _prompts[key] = model.create_voice_clone_prompt(
            ref_audio=request["reference"],
            ref_text=transcript,
            # Without a transcript only the speaker's timbre is used.
            x_vector_only_mode=transcript is None,
        )

    audio, rate = model.generate_voice_clone(
        text=request["text"],
        language=settings["language"],
        voice_clone_prompt=_prompts[key],
    )

    return _finish(
        request, audio[0], rate, load_seconds, time.perf_counter() - started
    )


def languages(request):
    model, _ = _load(request.get("model", "0.6b"))

    return {"languages": model.get_supported_languages()}


if __name__ == "__main__":
    serve({"synthesize": synthesize, "design": design, "languages": languages})
