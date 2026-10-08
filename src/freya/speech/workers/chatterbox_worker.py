"""
Chatterbox helper. Runs in Chatterbox's own environment.

One model is kept loaded at a time. Chatterbox adds its own inaudible
watermark to everything it generates; this helper writes the audio out
exactly as Chatterbox returns it and never touches that step.
"""
# worker_base comes first: importing it moves library chatter off the
# pipe that carries answers to Freya.
from worker_base import gpu_peak_megabytes, reset_gpu_peak, serve

import time

import soundfile as sf
import torch


DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

_loaded = {"name": None, "model": None}


def _load(name):
    if _loaded["name"] == name:
        return _loaded["model"], 0.0

    _loaded["name"] = None
    _loaded["model"] = None

    if DEVICE == "cuda":
        torch.cuda.empty_cache()

    started = time.perf_counter()

    if name in ("turbo", "nano"):
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        model = ChatterboxTurboTTS.from_pretrained(
            device=DEVICE,
            nano=(name == "nano"),
        )
    elif name == "multilingual":
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        model = ChatterboxMultilingualTTS.from_pretrained(
            device=torch.device(DEVICE),
            t3_model="v3",
        )
    else:
        raise ValueError(f"unknown Chatterbox model {name!r}")

    _loaded["name"] = name
    _loaded["model"] = model

    return model, time.perf_counter() - started


def synthesize(request):
    settings = request["settings"]
    model, load_seconds = _load(settings["model"])
    reset_gpu_peak()

    options = {
        "audio_prompt_path": request["reference"],
        "temperature": settings["temperature"],
    }

    if settings["model"] == "multilingual":
        options["language_id"] = settings["language"]
        options["exaggeration"] = settings["exaggeration"]
        options["cfg_weight"] = settings["cfg_weight"]

    started = time.perf_counter()
    audio = model.generate(request["text"], **options)
    generate_seconds = time.perf_counter() - started

    audio = audio.squeeze(0).detach().cpu().numpy()
    sf.write(request["output"], audio, model.sr)

    return {
        "sample_rate": model.sr,
        "load_seconds": round(load_seconds, 3),
        "generate_seconds": round(generate_seconds, 3),
        # Chatterbox returns the whole clip at once, so the first audio
        # arrives when generation finishes.
        "first_audio_seconds": round(generate_seconds, 3),
        "gpu_peak_mb": gpu_peak_megabytes(),
        "device": DEVICE,
    }


def watermark(request):
    """
    Report how strongly Chatterbox's watermark is detected in a file.
    """
    import librosa
    import perth

    audio, rate = librosa.load(request["path"], sr=None)
    found = perth.PerthImplicitWatermarker().get_watermark(
        audio,
        sample_rate=rate,
    )

    return {"watermark": float(found)}


def similarity(request):
    """
    How alike two recordings' speakers sound, from -1 to 1, using
    Chatterbox's speaker encoder. Used by the benchmark.
    """
    import librosa

    model, _ = _load(_loaded["name"] or "turbo")

    def speaker(path):
        audio, _ = librosa.load(path, sr=16000)

        return model.ve.embeds_from_wavs([audio], sample_rate=16000, as_spk=True)

    return {
        "similarity": float(
            speaker(request["reference"]) @ speaker(request["path"])
        )
    }


if __name__ == "__main__":
    serve(
        {
            "synthesize": synthesize,
            "watermark": watermark,
            "similarity": similarity,
        }
    )
