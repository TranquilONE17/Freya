import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ToolRequest:
    tool: str
    prompt: str


class FreyaToolRouter:
    """
    Stage 3A tool router.

    This first version intentionally uses deterministic routing instead
    of allowing the LLM to execute tools directly.

    That gives Freya natural-language image requests while keeping tool
    execution predictable and easy to debug.
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

    def route(
        self,
        user_input: str,
    ) -> Optional[ToolRequest]:
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

                prompt = prompt.rstrip(
                    " .!?"
                )

                if prompt:
                    return ToolRequest(
                        tool="image",
                        prompt=prompt,
                    )

        return None


if __name__ == "__main__":
    router = FreyaToolRouter()

    tests = [
        "Make me an image of a futuristic moon base.",
        "Can you create an image of a black spaceship?",
        "Generate a picture of a medieval castle.",
        "Draw an illustration of a cyberpunk city.",
        "What is the capital of France?",
        "Tell me about black holes.",
    ]

    for test in tests:
        result = router.route(test)

        print()
        print(f"Input: {test}")

        if result is None:
            print("Route: normal conversation")

        else:
            print(f"Route: {result.tool}")
            print(f"Prompt: {result.prompt}")
        