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
        - CPU status
        - memory (RAM) status
        - hardware inventory
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

    HARDWARE_PATTERNS = (
        r"\b(?:my|this|your|pc|computer|system|machine)(?:'s)? (?:hardware|components)\b",
        r"\b(?:hardware|components)\b.*\b(?:in|inside|of) (?:my|this|the|your) (?:pc|computer|machine|system|rig)\b",
        r"\bwhat (?:hardware|components) (?:do i have|is installed|are installed)\b",
        r"\bhardware (?:info|information|inventory|list|details|specs)\b",
        r"\b(?:system|computer|pc|machine|hardware)\b.*\bspecs\b",
        r"\bwhat(?:'s| is) (?:in|inside) (?:my|this) (?:pc|computer|machine)\b",
        r"\b(?:what|which) (?:motherboard|mainboard|bios)\b",
        r"\b(?:motherboard|mainboard|bios)\b.*\b(?:info|information|version|model|details)\b",
        r"\b(?:ram|memory) (?:modules|sticks|dimms)\b",
        r"\b(?:what|which) (?:network|wi-?fi|ethernet|sound|audio) (?:adapter|card|device)s?\b",
    )

    CPU_PATTERNS = (
        r"\b(?:cpu|processor)\b.*\b(?:status|usage|utilization|load|speed|cores|threads|busy|doing)\b",
        r"\b(?:status|usage|utilization|load|speed|cores|threads)\b.*\b(?:cpu|processor)\b",
        r"\bwhat(?:'s| is) my (?:cpu|processor)\b",
        r"\bwhat (?:cpu|processor) (?:do i have|is installed)\b",
        r"\bhow (?:busy|loaded|hard) is (?:my|the) (?:cpu|processor)\b",
        r"\bhow many (?:cpu )?(?:cores|threads)\b",
    )

    # "Memory" on its own also means Freya's long-term memory, so these
    # only match when the request is clearly about RAM.
    MEMORY_PATTERNS = (
        r"\b(?:ram|system memory|physical memory)\b.*\b(?:status|usage|used|using|free|available|left|remaining|installed|total)\b",
        r"\b(?:status|usage|used|using|free|available|installed|total)\b.*\b(?:ram|system memory|physical memory)\b",
        r"\bhow much\b.*\b(?:ram|system memory|physical memory)\b",
        r"\bhow much memory\b.*\b(?:used|using|in use|free|available|left|installed|do i have)\b",
        r"\bmemory usage\b",
    )

    DISK_PATTERNS = (
        r"\b(?:disks?|drives?|storage)\b.*\b(?:space|usage|free|available|left|remaining|full|info|information|status)\b",
        r"\bhow much\b.*\b(?:disks?|drives?|storage)\b.*\b(?:space|free|left|remaining)\b",
        r"\bhow much (?:free )?space do i have\b",
        r"\bhow full\b.*\b(?:disks?|drives?|storage)\b",
        r"\b(?:what|which|list|show)\b.*\b(?:disks|drives)\b",
        r"\bhow many (?:disks|drives)\b",
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

        if self._matches_any(text, self.HARDWARE_PATTERNS):
            return ToolRequest(tool="system.hardware")

        if self._matches_any(text, self.CPU_PATTERNS):
            return ToolRequest(tool="system.cpu")

        if self._matches_any(text, self.MEMORY_PATTERNS):
            return ToolRequest(tool="system.memory")

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
