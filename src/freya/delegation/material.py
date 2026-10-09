import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple


DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CLOUD_SETTINGS_PATH = DATA_DIR / "cloud_settings.json"

# The kinds of material a brief for a cloud model can be made from.
KIND_REQUEST = "request"
KIND_CONVERSATION = "conversation"
KIND_MEMORY = "memory"
KIND_PAST_CONVERSATION = "past-conversation"
KIND_TOOL_RESULT = "tool-result"
KIND_FILE = "file"
KIND_CODE = "code"

# What may happen to each kind.
ALLOWED = "allowed"
ASK = "ask"
NEVER = "never"
SETTINGS = (ALLOWED, ASK, NEVER)

# The owner's starting choices (2026-10-09): strict, loosened by hand.
DEFAULT_MATERIAL = {
    KIND_REQUEST: ALLOWED,
    KIND_CONVERSATION: ASK,
    KIND_MEMORY: NEVER,
    KIND_PAST_CONVERSATION: NEVER,
    KIND_TOOL_RESULT: ASK,
    KIND_FILE: ASK,
    KIND_CODE: ASK,
}
KINDS = tuple(DEFAULT_MATERIAL)

KIND_NAMES = {
    KIND_REQUEST: "the request",
    KIND_CONVERSATION: "this conversation",
    KIND_MEMORY: "stored memories",
    KIND_PAST_CONVERSATION: "past conversations",
    KIND_TOOL_RESULT: "tool results from this PC",
    KIND_FILE: "files and media",
    KIND_CODE: "Freya's own code",
}

# The kind each context source belongs to. A source missing from this
# table has no kind, and material with no kind never leaves.
SOURCE_KINDS = {
    "saved-memory": KIND_MEMORY,
    "conversation-summary": KIND_PAST_CONVERSATION,
    "conversation-passage": KIND_PAST_CONVERSATION,
    "past-recall": KIND_PAST_CONVERSATION,
    "media": KIND_FILE,
}


def kind_of_source(source: str) -> Optional[str]:
    return SOURCE_KINDS.get(source)


class CloudSettings:
    """
    The owner's choices about cloud models: which providers may be
    used at all, and what each kind of material may do. Kept in a JSON
    file next to the databases.

    A missing or unreadable file, an unknown provider, and any value
    that is not understood all mean the strict default: every provider
    off, and each kind at its starting setting.
    """

    def __init__(self, path=CLOUD_SETTINGS_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._material = dict(DEFAULT_MATERIAL)
        self._providers: Dict[str, bool] = {}
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return

        if not isinstance(data, dict):
            return

        material = data.get("material")

        if isinstance(material, dict):
            for kind in KINDS:
                if material.get(kind) in SETTINGS:
                    self._material[kind] = material[kind]

        providers = data.get("providers")

        if isinstance(providers, dict):
            self._providers = {
                name: True
                for name, enabled in providers.items()
                if isinstance(name, str) and enabled is True
            }

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "material": self._material,
                    "providers": self._providers,
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @property
    def material(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._material)

    def setting_for(self, kind: Optional[str]) -> str:
        with self._lock:
            return self._material.get(kind, NEVER)

    def set_material(self, kind: str, setting: str) -> None:
        if kind not in KINDS:
            raise ValueError(f"Unknown kind of material: {kind!r}")
        if setting not in SETTINGS:
            raise ValueError(f"Unknown setting: {setting!r}")

        with self._lock:
            if self._material[kind] != setting:
                self._material[kind] = setting
                self._save()

    def provider_enabled(self, provider: str) -> bool:
        with self._lock:
            return self._providers.get(provider, False)

    def enabled_providers(self) -> List[str]:
        with self._lock:
            return sorted(self._providers)

    def set_provider(self, provider: str, enabled: bool) -> None:
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError("A provider needs a name.")
        if not isinstance(enabled, bool):
            raise ValueError("A provider is either on or off.")

        with self._lock:
            if self._providers.get(provider, False) == enabled:
                return
            if enabled:
                self._providers[provider] = True
            else:
                del self._providers[provider]
            self._save()


@dataclass(frozen=True)
class BriefPart:
    """
    One piece of a brief, labelled with the kind of material it is.
    """

    kind: Optional[str]
    text: str
    source_id: str = ""


@dataclass(frozen=True)
class BriefReview:
    """
    What the owner's settings make of a brief bound for one provider.

    `send` holds the only parts that may be put in the request.
    `ask` lists the kinds that still need the owner's yes; while it is
    not empty, or the provider is off, nothing is ready to go.
    `withheld` holds the parts that were left out and can never go.
    """

    provider: str
    provider_enabled: bool
    send: Tuple[BriefPart, ...]
    ask: Tuple[str, ...]
    waiting: Tuple[BriefPart, ...]
    withheld: Tuple[BriefPart, ...]

    @property
    def ready(self) -> bool:
        return self.provider_enabled and not self.ask

    def describe(self) -> List[str]:
        """
        A description for the owner of what this provider would
        receive: kinds and amounts, never the text itself.
        """
        if not self.provider_enabled:
            return [f"{self.provider} is turned off. Nothing would be sent."]

        lines = [f"To {self.provider}:"]
        lines.extend(
            f"  {_amount(kind, parts)}"
            for kind, parts in _by_kind(self.send)
        )
        lines.extend(
            f"  {_amount(kind, parts)} (needs your permission)"
            for kind, parts in _by_kind(self.waiting)
        )

        if len(lines) == 1:
            lines.append("  nothing")

        if self.withheld:
            lines.append(
                "Left out, because it is set never to leave: "
                + ", ".join(
                    _amount(kind, parts)
                    for kind, parts in _by_kind(self.withheld)
                )
                + "."
            )

        return lines


def review_brief(
    parts,
    provider: str,
    settings: CloudSettings,
    approved_kinds: FrozenSet[str] = frozenset(),
) -> BriefReview:
    """
    Sort a brief's parts by what the owner's settings allow.

    `approved_kinds` are the ask-first kinds the owner has said yes to
    for this brief. An approval cannot release a kind set to never, or
    a part whose kind is not known.
    """
    send, waiting, withheld = [], [], []

    for part in parts:
        setting = (
            settings.setting_for(part.kind)
            if part.kind in KINDS
            else NEVER
        )

        if setting == ALLOWED or (
            setting == ASK and part.kind in approved_kinds
        ):
            send.append(part)
        elif setting == ASK:
            waiting.append(part)
        else:
            withheld.append(part)

    enabled = settings.provider_enabled(provider)

    return BriefReview(
        provider=provider,
        provider_enabled=enabled,
        send=tuple(send) if enabled else (),
        ask=tuple(kind for kind, _ in _by_kind(waiting)),
        waiting=tuple(waiting),
        withheld=tuple(withheld),
    )


def _by_kind(parts):
    """
    Parts grouped by kind, in the fixed order of KINDS, with parts of
    no known kind last.
    """
    groups = []

    for kind in KINDS + (None,):
        matching = [
            part for part in parts
            if (part.kind if part.kind in KINDS else None) == kind
        ]
        if matching:
            groups.append((kind, matching))

    return groups


def _amount(kind, parts):
    words = sum(len(part.text.split()) for part in parts)
    name = KIND_NAMES.get(kind, "unlabelled material")
    pieces = "1 piece" if len(parts) == 1 else f"{len(parts)} pieces"
    return f"{name}: {pieces}, about {words} words"
