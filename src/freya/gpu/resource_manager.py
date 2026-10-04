import json
import time
import urllib.error
import urllib.request


OLLAMA_URL = "http://127.0.0.1:11434"
COMFYUI_URL = "http://127.0.0.1:8188"


class GPUResourceManager:
    """
    Freya GPU Resource Manager v1.

    Coordinates GPU ownership between Ollama and ComfyUI.

    Stage 1 focuses on:
        - detecting loaded Ollama models
        - unloading Ollama models
        - detecting ComfyUI
        - requesting ComfyUI model unload/free-memory
        - reporting resource state

    No automatic switching is performed yet.
    """

    def __init__(
        self,
        ollama_url=OLLAMA_URL,
        comfyui_url=COMFYUI_URL,
    ):
        self.ollama_url = ollama_url.rstrip("/")
        self.comfyui_url = comfyui_url.rstrip("/")

    def _request_json(
        self,
        url,
        method="GET",
        payload=None,
        timeout=30,
    ):
        data = None
        headers = {}

        if payload is not None:
            data = json.dumps(
                payload
            ).encode("utf-8")

            headers[
                "Content-Type"
            ] = "application/json"

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )

        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            body = response.read()

            if not body:
                return {}

            return json.loads(
                body.decode("utf-8")
            )

    def ollama_available(self):
        try:
            self._request_json(
                f"{self.ollama_url}/api/ps"
            )
            return True

        except (
            urllib.error.URLError,
            TimeoutError,
        ):
            return False

    def comfyui_available(self):
        try:
            self._request_json(
                f"{self.comfyui_url}/system_stats"
            )
            return True

        except (
            urllib.error.URLError,
            TimeoutError,
        ):
            return False

    def get_ollama_models(self):
        try:
            response = self._request_json(
                f"{self.ollama_url}/api/ps"
            )

        except urllib.error.URLError:
            return []

        return response.get(
            "models",
            [],
        )

    def unload_ollama_model(
        self,
        model_name,
    ):
        print(
            "GPU Manager: unloading Ollama model "
            f"{model_name}..."
        )

        self._request_json(
            f"{self.ollama_url}/api/generate",
            method="POST",
            payload={
                "model": model_name,
                "keep_alive": 0,
            },
            timeout=60,
        )

    def unload_all_ollama_models(self):
        models = self.get_ollama_models()

        if not models:
            print(
                "GPU Manager: no Ollama models "
                "are currently loaded."
            )
            return

        for model in models:
            model_name = (
                model.get("name")
                or model.get("model")
            )

            if not model_name:
                continue

            self.unload_ollama_model(
                model_name
            )

        self.wait_for_ollama_unload()

    def wait_for_ollama_unload(
        self,
        timeout=30,
    ):
        start_time = time.monotonic()

        while True:
            models = self.get_ollama_models()

            if not models:
                print(
                    "GPU Manager: Ollama GPU "
                    "models released."
                )
                return True

            if (
                time.monotonic() - start_time
                > timeout
            ):
                raise TimeoutError(
                    "Timed out waiting for "
                    "Ollama models to unload."
                )

            time.sleep(0.25)

    def free_comfyui_memory(self):
        if not self.comfyui_available():
            print(
                "GPU Manager: ComfyUI is not running."
            )
            return False

        print(
            "GPU Manager: requesting ComfyUI "
            "model unload..."
        )

        self._request_json(
            f"{self.comfyui_url}/free",
            method="POST",
            payload={
                "unload_models": True,
                "free_memory": True,
            },
        )

        print(
            "GPU Manager: ComfyUI model "
            "unload requested."
        )

        return True

    def print_status(self):
        print()
        print("=== Freya GPU Resource Manager ===")

        if self.ollama_available():
            print("Ollama server: ONLINE")

            models = self.get_ollama_models()

            if models:
                print("Ollama loaded models:")

                for model in models:
                    name = (
                        model.get("name")
                        or model.get("model")
                        or "Unknown"
                    )

                    size_vram = model.get(
                        "size_vram",
                        0,
                    )

                    vram_gb = (
                        size_vram
                        / 1024
                        / 1024
                        / 1024
                    )

                    print(
                        f"  - {name} "
                        f"({vram_gb:.2f} GB VRAM)"
                    )

            else:
                print(
                    "Ollama loaded models: none"
                )

        else:
            print("Ollama server: OFFLINE")

        if self.comfyui_available():
            print("ComfyUI server: ONLINE")

        else:
            print("ComfyUI server: OFFLINE")

        print("==================================")
        print()


if __name__ == "__main__":
    manager = GPUResourceManager()

    manager.print_status()