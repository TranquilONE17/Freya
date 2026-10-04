import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ToolRequest:
    tool: str
    prompt: str = ""


class FreyaToolRouter:
    """
    Deterministic natural-language router for Freya tools.

    Stage 1C supports:
        - image generation
        - GPU status
        - disk status
        - basic system information

    Requests that do not clearly match a tool are left for normal
    conversation with the LLM.
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

    GPU_PATTERNS = (
        r"\b(?:gpu|graphics card)\b.*\b(?:status|usage|utilization|temperature|temp|memory|vram)\b",
        r"\b(?:status|usage|utilization|temperature|temp|memory|vram)\b.*\b(?:gpu|graphics card)\b",
        r"\bhow much\b.*\bvram\b",
        r"\bwhat(?:'s| is) my gpu\b",
        r"\bwhat gpu (?:do i have|is installed)\b",
    )

    DISK_PATTERNS = (
        r"\b(?:disk|drive|storage)\b.*\b(?:space|usage|free|available|left|remaining)\b",
        r"\bhow much\b.*\b(?:disk|drive|storage)\b.*\b(?:space|free|left|remaining)\b",
        r"\bhow much (?:free )?space do i have\b",
    )

    SYSTEM_PATTERNS = (
        r"\bwhat version of windows\b",
        r"\bwhat operating system\b",
        r"\b(?:system|computer|pc)\b.*\b(?:info|information|specs|details)\b",
        r"\bwhat computer (?:are you|am i) running\b",
        r"\bwhat python version\b",
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

        if self._matches_any(text, self.GPU_PATTERNS):
            return ToolRequest(tool="system.gpu")

        if self._matches_any(text, self.DISK_PATTERNS):
            return ToolRequest(tool="system.disk")

        if self._matches_any(text, self.SYSTEM_PATTERNS):
            return ToolRequest(tool="system.info")

        return None

    @staticmethod
    def _matches_any(text, patterns):
        return any(
            re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )
            for pattern in patterns
        )
