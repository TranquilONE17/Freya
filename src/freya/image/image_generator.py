import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


COMFYUI_URL = "http://127.0.0.1:8188"

WORKFLOW_PATH = (
    Path(__file__).resolve().parent
    / "workflows"
    / "z_image_turbo.json"
)

PROMPT_NODE = "57:27"
SAMPLER_NODE = "57:3"
SAVE_IMAGE_NODE = "9"


class FreyaImageGenerator:
    def __init__(
        self,
        server_url=COMFYUI_URL,
        workflow_path=WORKFLOW_PATH,
    ):
        self.server_url = server_url.rstrip("/")
        self.workflow_path = Path(workflow_path)

    def _request_json(
        self,
        endpoint,
        method="GET",
        payload=None,
        timeout=30,
    ):
        url = f"{self.server_url}{endpoint}"

        data = None
        headers = {}

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method,
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                return json.loads(
                    response.read().decode("utf-8")
                )

        except urllib.error.URLError as exc:
            raise RuntimeError(
                "Could not connect to ComfyUI at "
                f"{self.server_url}. "
                "Make sure ComfyUI is running."
            ) from exc

    def check_connection(self):
        stats = self._request_json(
            "/system_stats"
        )

        return stats

    def _load_workflow(self):
        if not self.workflow_path.exists():
            raise RuntimeError(
                "ComfyUI workflow file was not found:\n"
                f"{self.workflow_path}"
            )

        with self.workflow_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    def _prepare_workflow(
        self,
        prompt,
        seed=None,
    ):
        workflow = self._load_workflow()

        if PROMPT_NODE not in workflow:
            raise RuntimeError(
                f"Prompt node {PROMPT_NODE} "
                "was not found in the workflow."
            )

        if SAMPLER_NODE not in workflow:
            raise RuntimeError(
                f"Sampler node {SAMPLER_NODE} "
                "was not found in the workflow."
            )

        workflow[PROMPT_NODE]["inputs"]["text"] = prompt

        if seed is None:
            seed = random.randint(
                0,
                2**63 - 1,
            )

        workflow[SAMPLER_NODE]["inputs"]["seed"] = seed

        return workflow, seed

    def _queue_prompt(
        self,
        workflow,
    ):
        result = self._request_json(
            "/prompt",
            method="POST",
            payload={
                "prompt": workflow,
            },
        )

        prompt_id = result.get("prompt_id")

        if not prompt_id:
            raise RuntimeError(
                "ComfyUI did not return a prompt ID. "
                f"Response: {result}"
            )

        return prompt_id

    def _wait_for_completion(
        self,
        prompt_id,
        timeout=300,
        poll_interval=0.5,
    ):
        start_time = time.monotonic()

        while True:
            if time.monotonic() - start_time > timeout:
                raise TimeoutError(
                    "Image generation timed out."
                )

            history = self._request_json(
                f"/history/{prompt_id}"
            )

            if prompt_id in history:
                return history[prompt_id]

            time.sleep(poll_interval)

    def _get_output_images(
        self,
        history_entry,
    ):
        outputs = history_entry.get(
            "outputs",
            {},
        )

        output = outputs.get(
            SAVE_IMAGE_NODE,
            {},
        )

        images = output.get(
            "images",
            [],
        )

        if not images:
            raise RuntimeError(
                "ComfyUI finished the workflow, "
                "but no saved image was returned."
            )

        return images

    def get_image_url(
        self,
        image_info,
    ):
        query = urllib.parse.urlencode(
            {
                "filename": image_info["filename"],
                "subfolder": image_info.get(
                    "subfolder",
                    "",
                ),
                "type": image_info.get(
                    "type",
                    "output",
                ),
            }
        )

        return (
            f"{self.server_url}/view?"
            f"{query}"
        )

    def generate(
        self,
        prompt,
        seed=None,
        timeout=300,
    ):
        prompt = prompt.strip()

        if not prompt:
            raise ValueError(
                "Image prompt cannot be empty."
            )

        workflow, used_seed = (
            self._prepare_workflow(
                prompt,
                seed=seed,
            )
        )

        prompt_id = self._queue_prompt(
            workflow
        )

        history_entry = (
            self._wait_for_completion(
                prompt_id,
                timeout=timeout,
            )
        )

        images = self._get_output_images(
            history_entry
        )

        return {
            "prompt_id": prompt_id,
            "seed": used_seed,
            "images": images,
            "image_urls": [
                self.get_image_url(image)
                for image in images
            ],
        }


if __name__ == "__main__":
    generator = FreyaImageGenerator()

    print("Checking ComfyUI connection...")

    generator.check_connection()

    print("ComfyUI connection: OK")

    test_prompt = (
        "A futuristic lunar research station, "
        "photorealistic, cinematic lighting, "
        "highly detailed"
    )

    print()
    print("Generating test image...")
    print(f"Prompt: {test_prompt}")

    result = generator.generate(
        test_prompt
    )

    print()
    print("Image generation complete.")
    print(f"Prompt ID: {result['prompt_id']}")
    print(f"Seed: {result['seed']}")

    for image in result["images"]:
        print(
            "Output: "
            f"{image['filename']}"
        )

    for url in result["image_urls"]:
        print(
            "Image URL: "
            f"{url}"
        )