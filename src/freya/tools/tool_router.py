import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ToolRequest:
    tool: str
    prompt: str = ""


class FreyaToolRouter:
    """
    Deterministic natural-language router for image requests.

    Image generation needs the GPU handed over to ComfyUI, so it is
    recognised here before the language model is involved. Questions
    about the computer are no longer routed here: the model calls
    those tools itself.
    """

    IMAGE_PATTERNS = (
        r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?"
        r"(?:make|create|generate|draw|render)\s+"
        r"(?:me\s+)?(?:an?\s+)?image\s+(?:of\s+)?(.+)$",

        r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?"
        r"(?:make|create|generate|draw|render)\s+"
        r"(?:me\s+)?(?:a\s+)?picture\s+(?:of\s+)?(.+)$",

        r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?"
        r"(?:make|create|generate|draw|render)\s+"
        r"(?:me\s+)?(?:a\s+)?photo\s+(?:of\s+)?(.+)$",

        r"^(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?"
        r"(?:make|create|generate|draw|render)\s+"
        r"(?:me\s+)?(?:an?\s+)?illustration\s+(?:of\s+)?(.+)$",
    )

    def route(self, user_input: str) -> Optional[ToolRequest]:
        text = user_input.strip()

        if not text:
            return None

        for pattern in self.IMAGE_PATTERNS:
            match = re.match(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match:
                prompt = match.group(1).strip()
                prompt = prompt.rstrip(" .!?")

                if prompt:
                    return ToolRequest(
                        tool="image",
                        prompt=prompt,
                    )

        return None
