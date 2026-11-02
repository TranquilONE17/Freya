import json
import threading
import uuid
from typing import Callable, Dict, FrozenSet, List, Optional, Sequence, Tuple

from freya.core.model_runtime import ROLE_BACKGROUND
from freya.core.usage import ASK as VERDICT_ASK
from freya.core.usage import VALUE_NORMAL
from freya.delegation.compose import (
    TASK_KINDS,
    AvailableInput,
    PlanRefused,
    compose_brief,
    parse_plan,
)
from freya.delegation.dispatch import DispatchRefused
from freya.delegation.material import (
    KIND_CONVERSATION,
    KIND_NAMES,
    KIND_REQUEST,
    KIND_TOOL_RESULT,
)
from freya.delegation.screening import (
    MATCH_ALWAYS_PRIVATE,
    MATCH_MEANING,
    MATCH_NAME,
    MATCH_PHRASE,
)
from freya.delegation.window_requests import MAX_PHRASE, PROVIDER_LABELS


# How a turn began. Anything other than a typed or window turn is
# treated like a spoken one: speech is ambient input, not a decision.
ORIGIN_TYPED = "typed"
ORIGIN_WINDOW = "window"
ORIGIN_VOICE = "voice"
SELF_CONFIRMING_ORIGINS = (ORIGIN_TYPED, ORIGIN_WINDOW)

REQUEST_ID = "request"
RECENT_EXCHANGES = 3
# What one earlier exchange or tool result may add to a brief.
MAX_INPUT_CHARACTERS = 20_000
# The context authority clips every tool message to 2,400 bytes and
# turns a longer one into a broken excerpt. The whole result is kept
# under this, so the main model always gets valid JSON; the answer in
# full is in the card the owner sees.
MAX_RESULT_BYTES = 2_000
# The providers this version may hand work to, in order of preference.
PROVIDERS = ("anthropic",)
# The most times the sending checks are asked again after the owner
# answers a question they raised.
MAX_CHECK_ROUNDS = 4

# The answers each question offers.
ALLOW_ONCE = "once"
ALLOW_CONVERSATION = "conversation"
ALLOW_ALWAYS = "always"
DENY = "deny"
SEND = "send"
SEND_ANYWAY = "send_anyway"
NOT_PRIVATE = "not_private"
EXCEED = "exceed"
CANCEL = "cancel"

_HOW_MATCHED = {
    MATCH_ALWAYS_PRIVATE: "marked always private",
    MATCH_PHRASE: "words copied from your stored memories",
    MATCH_NAME: "a name or number from your stored memories",
    MATCH_MEANING: "close in meaning to a stored memory",
}


# What the main model is told the tool is for, and what it may pass.
# The evaluation offers the same words, so it measures the tool Freya
# really has. No argument is a place to write a sentence: only a kind
# from a fixed list and the ids of offered inputs.
WORK_DELEGATE_DESCRIPTION = (
    "Hands one piece of work to a stronger outside model and "
    "returns its answer. Use it for work you cannot do well "
    "yourself: long analysis, careful reasoning, review. Do "
    "not use it for conversation, for anything about the user "
    "personally, or for what you can answer directly. Give "
    "the kind of task and the ids of the inputs to send with "
    "it. You do not write the request; it is written from the "
    "inputs you choose. The answer comes from another model "
    "and may be wrong."
)
WORK_DELEGATE_PARAMETERS = {
    "kind": {
        "description": (
            "The kind of task, one of: " + ", ".join(TASK_KINDS) + "."
        ),
        "max_length": 20,
    },
    "inputs": {
        "description": (
            "The ids of the offered inputs to send with "
            "the work, separated by commas. May be empty."
        ),
        "max_length": 400,
        "optional": True,
    },
}


def delegation_hint(input_ids, spoken=False) -> str:
    """The sentence added to the tool hint for a turn that can delegate."""
    return (
        "Inputs you may send with delegated work: "
        + ", ".join(input_ids)
        + ". The Nth tool result you receive in this turn is tool-N, "
        "and only results that read this PC can be sent. "
        "When you used delegated work, say in your reply that part "
        "of the answer came from another model, and name it. The user "
        "is shown that model's answer in full under its own name, so "
        "do not repeat it: add what you make of it."
        + (
            " This turn was spoken, and your reply will be read aloud: "
            "give only your own short interpretation."
            if spoken
            else ""
        )
    )


class DelegationRefused(Exception):
    """
    Work was not handed over. The message is fixed wording that is
    safe to give the model, to the audit log and to the owner: it
    never holds a brief's text, what screening matched, or what the
    vendor's program said.
    """


class DelegationTurn:
    """
    What one turn knows about handing work over: the inputs offered
    for it, how it began, and whether work has already been handed
    over. Freya's code builds it before the model is first called.
    """

    def __init__(
        self,
        origin: str,
        inputs: Sequence[AvailableInput],
        accepts_tool_result: Callable[[str], bool] = lambda tool_name: False,
    ):
        self.origin = origin
        self._inputs: List[AvailableInput] = list(inputs)
        self._accepts = accepts_tool_result
        self._tool_results = 0
        # Set when a brief is about to be sent: one delegation a turn.
        self.delegated = False
        # Set when the owner said no: the model is not to ask again.
        self.declined = False
        # What the record says about the kind of work being handed over.
        self.measured: List[str] = []

    @property
    def inputs(self) -> Tuple[AvailableInput, ...]:
        return tuple(self._inputs)

    @property
    def input_ids(self) -> List[str]:
        return [item.input_id for item in self._inputs]

    @property
    def needs_confirmation(self) -> bool:
        return self.origin not in SELF_CONFIRMING_ORIGINS

    def add_tool_result(self, tool_name, text) -> Optional[str]:
        """
        Note a tool result obtained in this turn. The Nth result is
        `tool-N`, so the model can count them. Only the results of tools
        that read this PC are offered; a tool that returns saved
        memories, past conversations or media records is not, whatever
        its result looks like. Returns the id offered, or None.
        """
        self._tool_results += 1

        if not isinstance(tool_name, str) or not isinstance(text, str):
            return None
        if not text.strip():
            return None

        try:
            accepted = self._accepts(tool_name) is True
        except Exception:
            accepted = False

        if not accepted:
            return None
        if _is_only_an_error(text):
            return None

        item = AvailableInput(
            f"tool-{self._tool_results}",
            KIND_TOOL_RESULT,
            text[:MAX_INPUT_CHARACTERS],
        )
        self._inputs.append(item)

        return item.input_id


def _is_only_an_error(text: str) -> bool:
    try:
        value = json.loads(text)
    except ValueError:
        return False

    return isinstance(value, dict) and set(value) == {"error"}


def recent_exchanges(messages, count=RECENT_EXCHANGES) -> List[Tuple[str, str]]:
    """
    The last `count` exchanges of the live conversation, most recent
    first, as (what the owner said, what Freya replied). A message
    that has no partner is skipped.
    """
    turns = [
        message for message in messages
        if isinstance(message, dict)
        and message.get("role") in ("user", "assistant")
        and isinstance(message.get("content"), str)
    ]
    found: List[Tuple[str, str]] = []
    index = len(turns)

    while index >= 2 and len(found) < count:
        reply, said = turns[index - 1], turns[index - 2]

        if said["role"] == "user" and reply["role"] == "assistant":
            found.append((said["content"], reply["content"]))
            index -= 2
        else:
            index -= 1

    return found


def build_inputs(user_input: str, messages) -> List[AvailableInput]:
    """
    The inputs offered for a turn, built once before the model is
    called. The kind of each comes from where Freya's code took it,
    never from the model and never from what the text says.

    Saved memories, conversation summaries, recalled passages and
    media records are not offered at all, whatever the owner's
    settings say, and nothing else is: a source that is not listed
    here has no way into a brief.
    """
    inputs = [AvailableInput(REQUEST_ID, KIND_REQUEST, user_input)]

    # Only what the owner said. Freya's own replies often restate what
    # she recalled from memory, so offering them as "this conversation"
    # would let memory leave under another label.
    for number, (said, _) in enumerate(recent_exchanges(messages), 1):
        inputs.append(
            AvailableInput(
                f"turn-{number}",
                KIND_CONVERSATION,
                said[:MAX_INPUT_CHARACTERS],
            )
        )

    return inputs


def _split_ids(text) -> List[str]:
    if not isinstance(text, str):
        return []

    return [part.strip() for part in text.split(",") if part.strip()]


class TurnDelegation:
    """
    Lets Freya's main model hand one piece of work to an outside model
    during an ordinary turn, and puts every question to the owner.

    The model chooses a kind of task and the ids of inputs Freya's
    code offered; it has no way to write a word of the request. Code
    does the rest: compose the brief from cleared material, ask the
    owner whatever the settings require, authorize it through the
    dispatcher, send it, and give the answer back as an untrusted tool
    result.

    `ask_owner(prompt)` shows a question in the owner's window and
    returns the id of the answer chosen, or None when there is none.
    It is given to this class so that nothing here imports the
    gateway.
    """

    def __init__(
        self,
        cloud,
        chat: Callable[..., str],
        ask_owner: Callable[[dict], Optional[str]],
        window_connected: Callable[[], bool],
        mark_not_private: Callable[[str], bool],
        accepts_tool_result: Callable[[str], bool] = lambda tool_name: False,
        measured: Callable[[str, str], List[str]] = lambda kind, route: [],
        add_rule: Optional[Callable[[str, str, List[str]], bool]] = None,
    ):
        # Records the owner's "allow permanently". Without it that
        # answer is not offered.
        self._add_rule = add_rule
        self._measured = measured
        self._cloud = cloud
        self._chat = chat
        self._ask_owner = ask_owner
        self._window_connected = window_connected
        self._mark_not_private = mark_not_private
        self._accepts_tool_result = accepts_tool_result
        self._lock = threading.Lock()
        self._current: Optional[DelegationTurn] = None
        # Kinds the owner allowed for the rest of this conversation,
        # by provider. They are kept in memory only.
        self._approved: Dict[str, FrozenSet[str]] = {}

    # -- the turn --------------------------------------------------

    def begin_turn(self, user_input: str, messages, origin: str) -> DelegationTurn:
        turn = DelegationTurn(
            origin,
            build_inputs(user_input, messages),
            self._accepts_tool_result,
        )

        with self._lock:
            self._current = turn

        return turn

    def end_turn(self, turn: Optional[DelegationTurn]) -> None:
        with self._lock:
            if self._current is turn:
                self._current = None

    @property
    def current_turn(self) -> Optional[DelegationTurn]:
        with self._lock:
            return self._current

    # -- whether the tool can work --------------------------------

    def _route(self):
        """The provider this version would use, and its route."""
        for provider in PROVIDERS:
            route = self._cloud.routes.get(provider)

            if route is not None and self._cloud.settings.provider_enabled(
                provider
            ):
                return provider, route

        return None

    def available(self) -> bool:
        """
        Whether handing work over can work now: a turn is under way, a
        provider with a route is switched on, and a window is there to
        ask the owner in. When it cannot, the tool is not offered.
        """
        return (
            self.current_turn is not None
            and self._route() is not None
            and self._window_connected() is True
        )

    def hint(self) -> str:
        """The sentence added to the tool hint for this turn."""
        turn = self.current_turn

        if turn is None or not self.available():
            return ""

        return delegation_hint(turn.input_ids, turn.origin == ORIGIN_VOICE)

    # -- the tool --------------------------------------------------

    def delegate(self, kind, inputs="") -> dict:
        """
        Hand one piece of work over, as the model asked. Raises
        DelegationRefused, with fixed wording, whenever it does not.
        """
        turn = self.current_turn

        if turn is None:
            raise DelegationRefused("There is no turn to hand work over from.")
        if turn.delegated:
            raise DelegationRefused(
                "Work was already handed over in this turn. "
                "Only one piece of work can be."
            )
        if turn.declined:
            raise DelegationRefused(
                "The user already said no to handing work over in this turn."
            )

        try:
            plan = parse_plan(
                {"kind": kind, "inputs": _split_ids(inputs)}, turn.inputs,
            )
        except PlanRefused as refused:
            raise DelegationRefused(
                f"{refused} Kinds: {', '.join(TASK_KINDS)}. "
                f"Inputs offered: {', '.join(turn.input_ids)}."
            )

        chosen = self._route()

        if chosen is None:
            raise DelegationRefused("No outside model is switched on.")

        provider, route = chosen
        waiting = self._cloud.hold_reason(provider)

        if waiting:
            # Said before the user is asked anything: there is no
            # point in a prompt for a brief that cannot go.
            raise DelegationRefused(f"{waiting} Nothing was sent.")

        # What the record says about this kind of work. It informs the
        # owner and the model; it does not refuse or redirect, and it
        # changes nothing about what is sent.
        try:
            measured = [
                str(line)
                for line in self._measured(plan.kind, route.route_id)
            ]
        except Exception:
            measured = []

        turn.measured = measured
        brief = self._compose(plan, turn, provider)

        if brief.review.ask:
            brief = self._approve(plan, turn, provider, brief)

        if not brief.ready:
            raise DelegationRefused(
                "Nothing in this request is allowed to leave this computer."
            )

        # Speech never confirms: a spoken turn is always asked, even
        # when no setting needs an answer.
        if turn.needs_confirmation:
            self._require(
                turn,
                self._confirmation_prompt(provider, brief),
                SEND,
                "The user did not confirm sending this, so nothing was sent.",
            )

        authorization = self._authorize(turn, provider, route, brief)
        turn.delegated = True

        try:
            reply = self._cloud.dispatcher.send(authorization, brief.text)
        except DispatchRefused as refused:
            turn.delegated = False
            raise DelegationRefused(f"{refused.reason} Nothing was sent.")
        except Exception as error:
            waiting = self._cloud.hold_reason(provider)

            if waiting:
                raise DelegationRefused(
                    f"{waiting} The request was received but not answered."
                )
            if getattr(error, "sent", True) is False:
                raise DelegationRefused(
                    "Claude could not be asked. The request was not sent."
                )
            raise DelegationRefused(
                "Claude could not be asked. The request may have been "
                "received."
            )

        return self._answer(provider, reply, measured)

    @staticmethod
    def _answer(provider, reply, measured=()) -> dict:
        """
        The tool result for the main model: who answered, what the
        record says, and as much of the answer as fits her context.
        The owner sees the whole answer in its card.
        """
        text = getattr(reply, "text", "")
        text = text if isinstance(text, str) else ""
        result = {
            "from": PROVIDER_LABELS.get(provider, provider),
            "model": str(getattr(reply, "model", "") or "")[:80],
            "answer": text,
            "shown_to_user": (
                "The user sees this answer in full, under the name above. "
                "Do not repeat it; say what you make of it."
            ),
        }

        if measured:
            result["measured"] = " ".join(measured)

        def size():
            return len(json.dumps(result, default=str).encode("utf-8"))

        if size() > MAX_RESULT_BYTES or getattr(reply, "truncated", False):
            result["shortened"] = True
            result["note"] = (
                "Only the start of the answer is here; the user sees all of it."
            )

            # The longest start of the answer that fits, found by
            # halving. Whole characters are cut, and the size is taken
            # from the same encoding the tool result is sent in, where
            # one character can cost six bytes.
            low, high = 0, len(text)

            while low < high:
                middle = (low + high + 1) // 2
                result["answer"] = text[:middle]

                if size() <= MAX_RESULT_BYTES:
                    low = middle
                else:
                    high = middle - 1

            result["answer"] = text[:low]

        return result

    # -- composing and approving ----------------------------------

    def _writer(self, messages: List[dict]) -> str:
        """
        The brief writer: a fresh call to the local model, shown
        exactly what `compose.writer_messages` made and nothing else.
        """
        try:
            return self._chat(messages, role=ROLE_BACKGROUND)
        except Exception:
            raise DelegationRefused(
                "The local model that writes the request is not available."
            )

    def _compose(self, plan, turn, provider, approved=None):
        if approved is None:
            approved = self._approved.get(provider, frozenset())

        # Whatever else was allowed, the owner's standing rules for a
        # task of this kind apply as well.
        approved = frozenset(approved) | self._cloud.settings.rule_kinds(
            provider, plan.kind,
        )

        try:
            return compose_brief(
                plan,
                turn.inputs,
                provider,
                self._cloud.settings,
                self._writer,
                approved,
            )
        except PlanRefused as refused:
            raise DelegationRefused(str(refused))

    def _approve(self, plan, turn, provider, brief):
        """
        Ask about the kinds of material set to ask first, then compose
        again with what the owner allowed.
        """
        kinds = frozenset(brief.review.ask)
        answer = self._ask(self._approval_prompt(provider, brief, plan.kind))
        offered = [ALLOW_ONCE, ALLOW_CONVERSATION]

        if self._add_rule is not None:
            offered.append(ALLOW_ALWAYS)

        if answer not in offered:
            turn.declined = True
            raise DelegationRefused(
                "The user did not allow that material to be sent, "
                "so nothing was sent."
            )

        approved = self._approved.get(provider, frozenset()) | kinds

        if answer == ALLOW_CONVERSATION:
            self._approved[provider] = approved
        elif answer == ALLOW_ALWAYS:
            # Exactly what was shown: this provider, this kind of
            # task, these kinds of material.
            if not self._add_rule(provider, plan.kind, sorted(kinds)):
                raise DelegationRefused(
                    "That could not be recorded as always allowed. "
                    "Nothing was sent."
                )

        brief = self._compose(plan, turn, provider, approved)

        if brief.review.ask:
            raise DelegationRefused(
                "Your cloud settings changed while you decided. "
                "Nothing was sent."
            )

        return brief

    # -- the sending checks ---------------------------------------

    def _authorize(self, turn, provider, route, brief):
        """
        Pass the brief through the dispatcher, putting to the owner
        each question the checks raise. The value and urgency are
        fixed here; the model's suggestions are not passed on.
        """
        released = False
        exceed = False
        task_id = "turn-" + uuid.uuid4().hex[:12]

        for _ in range(MAX_CHECK_ROUNDS):
            try:
                return self._cloud.dispatcher.authorize(
                    brief,
                    route.route_id,
                    task_id,
                    value=VALUE_NORMAL,
                    urgent=False,
                    owner_released_hold=released,
                    owner_agreed_to_exceed=exceed,
                )
            except DispatchRefused as refused:
                screening = refused.screening
                assessment = refused.assessment

                if screening is not None and screening.held:
                    answer = self._ask(
                        self._hold_prompt(provider, brief, screening)
                    )

                    if answer == SEND_ANYWAY:
                        released = True
                    elif answer == NOT_PRIVATE:
                        self._clear_matches(screening)
                    else:
                        self._decline(turn)
                elif assessment is not None and assessment.verdict == VERDICT_ASK:
                    answer = self._ask(
                        self._limit_prompt(provider, brief, assessment)
                    )

                    if answer == EXCEED:
                        exceed = True
                    else:
                        self._decline(turn)
                else:
                    raise DelegationRefused(refused.reason)

        raise DelegationRefused(
            "The checks before sending did not settle. Nothing was sent."
        )

    def _clear_matches(self, screening) -> None:
        for match in screening.matches:
            if not self._mark_not_private(match.text):
                raise DelegationRefused(
                    "That could not be recorded as not private. "
                    "Nothing was sent."
                )

    @staticmethod
    def _decline(turn) -> None:
        turn.declined = True
        raise DelegationRefused(
            "The user chose not to send this, so nothing was sent."
        )

    def _require(self, turn, prompt, wanted, refusal) -> None:
        if self._ask(prompt) != wanted:
            turn.declined = True
            raise DelegationRefused(refusal)

    # -- the questions --------------------------------------------

    def _ask(self, prompt: dict) -> Optional[str]:
        """
        Put one question to the owner. Only one of the answers the
        question offered counts; anything else, and no answer at all,
        is a denial.
        """
        turn = self.current_turn

        if turn is not None and turn.measured:
            # What the record says about this kind of work, after the
            # description of what would be sent.
            prompt = {**prompt, "lines": [*prompt["lines"], *turn.measured]}

        try:
            answer = self._ask_owner(prompt)
        except Exception:
            return None

        offered = {choice["id"] for choice in prompt["choices"]}

        return answer if isinstance(answer, str) and answer in offered else None

    @staticmethod
    def _prompt(kind, provider, review, text, label, choices, **more) -> dict:
        return {
            "kind": kind,
            "provider": PROVIDER_LABELS.get(provider, provider),
            "lines": review.describe(),
            "text": text,
            "text_label": label,
            "choices": [
                {"id": choice, "label": words} for choice, words in choices
            ],
            **more,
        }

    _SENT_LABEL = "The request exactly as it would be sent"

    def _approval_prompt(self, provider, brief, task="") -> dict:
        review = brief.review
        choices = [
            (ALLOW_ONCE, "Allow once"),
            (ALLOW_CONVERSATION, "Allow for this conversation"),
        ]

        if self._add_rule is not None and task:
            asked = ", ".join(
                KIND_NAMES.get(kind, kind) for kind in sorted(review.ask)
            )
            choices.append((
                ALLOW_ALWAYS,
                f"Always allow for {task} tasks ({asked})",
            ))

        choices.append((DENY, "Deny"))
        shown = [
            part for part in brief.parts
            if part in review.send or part in review.waiting
        ]
        material = "\n\n".join(
            f"[{number}] ({KIND_NAMES.get(part.kind, 'unlabelled material')})"
            f"\n{part.text}"
            for number, part in enumerate(shown, 1)
        )

        return self._prompt(
            "approval", provider, review, material,
            "The material that would be sent. The task description is "
            "written after you answer.",
            choices,
        )

    def _confirmation_prompt(self, provider, brief) -> dict:
        return self._prompt(
            "confirmation", provider, brief.review, brief.text,
            self._SENT_LABEL,
            [(SEND, "Send"), (CANCEL, "Cancel")],
            reason="You spoke this request, so Freya asks before sending.",
        )

    def _hold_prompt(self, provider, brief, screening) -> dict:
        matches = [
            {"how": _HOW_MATCHED.get(match.kind, "a match"), "text": match.text}
            for match in screening.matches
        ]
        fixed = any(
            match.kind == MATCH_ALWAYS_PRIVATE for match in screening.matches
        )

        if fixed:
            choices = [(CANCEL, "Cancel")]
            reason = (
                "Something in this request is marked always private. "
                "It cannot be sent."
            )
        else:
            choices = [(SEND_ANYWAY, "Send once anyway")]
            reason = "This request matches something in your personal store."

            if all(len(match.text) <= MAX_PHRASE for match in screening.matches):
                choices.append((NOT_PRIVATE, "This is not private"))

            choices.append((CANCEL, "Cancel"))

        return self._prompt(
            "hold", provider, brief.review, brief.text, self._SENT_LABEL,
            choices, reason=reason, matches=matches,
        )

    def _limit_prompt(self, provider, brief, assessment) -> dict:
        return self._prompt(
            "limit", provider, brief.review, brief.text, self._SENT_LABEL,
            [(EXCEED, "Go over this once"), (CANCEL, "Cancel")],
            reason=assessment.reason,
        )
