import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from freya.core.usage import GO, Assessment, UsageLedger
from freya.delegation.compose import ComposedBrief
from freya.delegation.material import CloudSettings
from freya.delegation.screening import (
    MATCH_ALWAYS_PRIVATE,
    Corrections,
    ScreeningResult,
    screen_brief,
)


DATA_DIR = Path(__file__).resolve().parents[3] / "data"
SENT_BRIEFS_PATH = DATA_DIR / "sent_briefs.jsonl"

# How long an authorization stays good. It is meant to be used at once.
AUTHORIZATION_SECONDS = 120
# What a reply may add to the estimate, in the route's unit.
REPLY_ALLOWANCE = 4096


def brief_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """A deliberately high count: every byte a token, plus the reply."""
    return len(text.encode("utf-8")) + REPLY_ALLOWANCE


@dataclass(frozen=True)
class Route:
    """
    One way of reaching one model. `ask` sends a brief and returns
    something with `text` and `tokens`; when it fails, the exception's
    `sent` attribute says whether the brief may have left.
    """

    route_id: str
    provider: str
    ask: Callable[[str], object]
    unit: str = "tokens"
    estimate: Callable[[str], int] = estimate_tokens


class DispatchRefused(Exception):
    """
    A brief was not authorized or not sent. `review`, `screening` and
    `assessment` carry whichever check said no, for the owner's prompt.
    """

    def __init__(self, reason, *, review=None, screening=None, assessment=None):
        super().__init__(reason)
        self.reason = reason
        self.review = review
        self.screening = screening
        self.assessment = assessment


@dataclass(frozen=True)
class Authorization:
    """
    Proof that one exact brief passed every check for one route. It
    names the brief by its hash, so no other text can be sent with it.
    """

    brief_hash: str
    route_id: str
    provider: str
    settings_revision: int
    event_id: int
    issued: float
    serial: int


class SentBriefs:
    """
    The owner's own record of every brief that left this machine, or
    may have. It is personal data and stays here; it is not the audit
    log, which never holds a brief's text.
    """

    def __init__(self, path=SENT_BRIEFS_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(self, provider, route_id, text, outcome, at=None) -> None:
        moment = at or datetime.now(timezone.utc)
        line = json.dumps({
            "at": moment.isoformat(),
            "provider": provider,
            "route": route_id,
            "outcome": outcome,
            "text": text,
        }, ensure_ascii=False)

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as output:
                output.write(line + "\n")
                output.flush()
                os.fsync(output.fileno())

    def entries(self) -> List[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        return [json.loads(line) for line in lines if line.strip()]


class Dispatcher:
    """
    The one place a brief can leave from.

    Sending takes two steps. `authorize` runs every check on a
    composed brief and reserves its usage: the provider's switch, the
    material sorting, screening against the personal store, and the
    usage ledger. `send` accepts only an authorization made here, for
    the same text, once, soon, and only if the owner's settings have
    not changed since. A route's own `ask` is never called from
    anywhere else.
    """

    def __init__(
        self,
        settings: CloudSettings,
        ledger: UsageLedger,
        routes: Iterable[Route],
        memories: Callable[[], Iterable[Tuple[str, str]]],
        sent: SentBriefs,
        corrections: Optional[Corrections] = None,
        closeness=None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._settings = settings
        self._ledger = ledger
        self._routes: Dict[str, Route] = {r.route_id: r for r in routes}
        self._memories = memories
        self._sent = sent
        self._corrections = corrections
        self._closeness = closeness
        self._clock = clock
        self._lock = threading.Lock()
        self._serial = 0
        self._open: Dict[int, Authorization] = {}

    def screen(self, text: str) -> ScreeningResult:
        return screen_brief(
            text, self._memories(), self._corrections, self._closeness,
        )

    def authorize(
        self,
        brief: ComposedBrief,
        route_id: str,
        task_id: str,
        *,
        owner_released_hold: bool = False,
        owner_agreed_to_exceed: bool = False,
        now=None,
    ) -> Authorization:
        """
        Check one composed brief for one route and reserve its usage.

        `owner_released_hold` is the owner answering "send it once
        anyway" to a held brief. It does not release a match on
        something marked always private.
        """
        route = self._routes.get(route_id)

        if route is None:
            raise DispatchRefused("There is no such route.")
        if brief.provider != route.provider:
            raise DispatchRefused("The brief was composed for another provider.")
        if not self._settings.provider_enabled(route.provider):
            raise DispatchRefused(f"{route.provider} is turned off.")
        if not brief.ready or not brief.review.ready:
            raise DispatchRefused(
                "Some of the material still needs your permission.",
                review=brief.review,
            )

        revision = self._settings.revision
        screening = self.screen(brief.text)

        if screening.held:
            fixed = any(
                match.kind == MATCH_ALWAYS_PRIVATE
                for match in screening.matches
            )
            if fixed or not owner_released_hold:
                raise DispatchRefused(
                    "The brief contains something marked always private."
                    if fixed
                    else "The brief matches something in your personal store.",
                    screening=screening,
                )

        assessment = self._ledger.reserve(
            route.route_id,
            route.unit,
            route.estimate(brief.text),
            task_id,
            value=brief.plan.value,
            urgent=brief.plan.urgent,
            owner_agreed_to_exceed=owner_agreed_to_exceed,
            now=now,
        )

        if assessment.verdict != GO or assessment.event_id is None:
            raise DispatchRefused(assessment.reason, assessment=assessment)

        with self._lock:
            self._serial += 1
            authorization = Authorization(
                brief_hash=brief_hash(brief.text),
                route_id=route.route_id,
                provider=route.provider,
                settings_revision=revision,
                event_id=assessment.event_id,
                issued=self._clock(),
                serial=self._serial,
            )
            self._open[authorization.serial] = authorization

        return authorization

    def send(self, authorization: Authorization, text: str):
        """
        Send the brief an authorization was made for, and nothing else.
        """
        with self._lock:
            known = self._open.pop(getattr(authorization, "serial", None), None)

        if known is None or known != authorization:
            raise DispatchRefused("That authorization is not valid.")

        route = self._routes[authorization.route_id]

        def refuse(reason):
            self._ledger.release(authorization.event_id)
            return DispatchRefused(reason)

        if brief_hash(text) != authorization.brief_hash:
            raise refuse("The text is not the brief that was authorized.")
        if self._clock() - authorization.issued > AUTHORIZATION_SECONDS:
            raise refuse("The authorization is too old.")
        if self._settings.revision != authorization.settings_revision:
            raise refuse("Your cloud settings changed; the brief must be checked again.")
        if not self._settings.provider_enabled(route.provider):
            raise refuse(f"{route.provider} is turned off.")

        try:
            reply = route.ask(text)
        except Exception as exc:
            if getattr(exc, "sent", True):
                # It may have left, and what it used is not known.
                self._ledger.mark_unknown(authorization.event_id)
                self._sent.record(
                    route.provider, route.route_id, text, "outcome unknown",
                )
            else:
                self._ledger.release(authorization.event_id)
            raise

        self._ledger.settle(
            authorization.event_id, max(0, int(getattr(reply, "tokens", 0))),
        )
        self._sent.record(route.provider, route.route_id, text, "answered")

        return reply
