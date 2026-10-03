import json
import re

import ollama

from config import MODEL


ALLOWED_MEMORY_TYPES = {
    "preference",
    "person",
    "goal",
    "project",
    "hardware",
    "plan",
    "fact",
    "other",
}

ALLOWED_MEMORY_RELATIONSHIPS = {
    "duplicate",
    "complementary",
    "conflict",
    "uncertain",
}


def chat(messages):
    response = ollama.chat(
        model=MODEL,
        messages=messages,
    )

    return response["message"]["content"]


def _normalize_key(memory_key):
    memory_key = memory_key.strip().lower()

    memory_key = re.sub(
        r"[^a-z0-9]+",
        "_",
        memory_key,
    )

    memory_key = memory_key.strip("_")

    return memory_key


def _parse_memory_result(result):
    try:
        data = json.loads(result)
    except json.JSONDecodeError:
        return None

    if not data.get("remember"):
        return None

    content = str(
        data.get("content", "")
    ).strip()

    memory_type = str(
        data.get("type", "other")
    ).strip().lower()

    memory_key = str(
        data.get("key", "")
    ).strip()

    if memory_type not in ALLOWED_MEMORY_TYPES:
        memory_type = "other"

    memory_key = _normalize_key(
        memory_key
    )

    if not content or not memory_key:
        return None

    return {
        "type": memory_type,
        "key": memory_key,
        "content": content,
    }


def evaluate_memory(user_input):
    prompt = f"""
You are the long-term memory extractor for a personal AI assistant
named Freya.

Determine whether the user's message contains durable information
that would be useful in future conversations.

Useful memories include:
- Personal preferences
- Names and relationships
- Long-term goals
- Project decisions
- Hardware or system information
- Stable plans
- Important facts explicitly provided by the user

Do NOT save:
- Ordinary questions
- Greetings
- Temporary conversational details
- General knowledge
- Commands
- Speculation
- Information stated only by the assistant
- Information useful only for the current conversation

Classify useful memories as one of:

preference
person
goal
project
hardware
plan
fact
other

You must also create a stable semantic memory key.

The key represents WHAT PROPERTY the memory describes,
not the current value of that property.

Examples:

"My favorite color is blue."
key: favorite_color

"My favorite color is green now."
key: favorite_color

"My favorite music genre is jazz."
key: favorite_music_genre

"My gaming PC has an RTX 4090."
key: gaming_pc_gpu

"I upgraded my gaming PC to an RTX 5090."
key: gaming_pc_gpu

"I want Freya's voice system to run locally."
key: freya_voice_local_goal

"I want the media server installed in the server rack."
key: media_server_location

Keys must:
- Be lowercase
- Use underscores
- Be concise
- Describe the underlying property
- NOT contain the current value when avoidable

If the message indicates that previous information has changed,
such as words like:
- actually
- now
- instead
- changed
- upgraded
- replaced
- no longer

the new memory should still use the SAME key as the old property.

Return ONLY valid JSON.

If something should be remembered:

{{
    "remember": true,
    "type": "preference",
    "key": "favorite_music_genre",
    "content": "User's favorite music genre is jazz."
}}

If nothing should be remembered:

{{
    "remember": false
}}

User message:
{user_input}
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        format="json",
    )

    result = response[
        "message"
    ]["content"].strip()

    return _parse_memory_result(
        result
    )


def classify_legacy_memory(content):
    prompt = f"""
You are analyzing an OLD long-term memory from Freya's
memory database.

This memory was created before semantic memory types and
semantic memory keys existed.

Your job is ONLY to classify the existing memory.

Do not add new facts.
Do not change the meaning.
Do not infer details that are not present.
Do not decide whether to delete anything.
Do not decide whether to merge anything.

Classify the memory as exactly one of:

preference
person
goal
project
hardware
plan
fact
other

Also assign a stable semantic key.

The key describes WHAT PROPERTY the memory represents,
not its current value.

Examples:

Memory:
"my favorite color is blue"

type: preference
key: favorite_color

Memory:
"my gaming PC has an RTX 4090"

type: hardware
key: gaming_pc_gpu

Memory:
"I want the media server installed in the server rack"

type: plan
key: media_server_location

Memory:
"User plans to eventually move their media server into the
same rack as Freya's AI hardware."

type: plan
key: media_server_location

Memory:
"User wants Freya's voice system to eventually run completely
locally."

type: goal
key: freya_voice_local_goal

Keys must:
- Be lowercase
- Use underscores
- Be concise
- Describe the underlying property
- NOT contain the current value when avoidable

Return ONLY valid JSON in this exact general form:

{{
    "remember": true,
    "type": "preference",
    "key": "favorite_color",
    "content": "the exact original memory"
}}

IMPORTANT:
The content field must contain the EXACT original memory text.
Do not rewrite it.

Original memory:
{content}
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        format="json",
    )

    result = response[
        "message"
    ]["content"].strip()

    candidate = _parse_memory_result(
        result
    )

    if candidate is None:
        return None

    candidate["content"] = content

    return candidate


def compare_memories(
    memory_a,
    memory_b,
):
    prompt = f"""
You are Freya's memory relationship analyzer.

Compare two existing long-term memories.

This operation is READ-ONLY.

You are NOT deciding whether anything should be deleted,
merged, or changed.

Classify the relationship as exactly one of:

duplicate
complementary
conflict
uncertain

Definitions:

duplicate:
The two memories communicate essentially the same durable
information. Wording or amount of detail may differ, but
keeping both would be substantially redundant.

complementary:
The memories concern the same general subject but represent
different facts that can both be true and are useful
independently.

conflict:
The memories describe the same underlying property but give
incompatible values, states, plans, or preferences.

uncertain:
There is not enough information to safely determine whether
the memories are duplicate, complementary, or conflicting.

Examples:

Memory A:
"User's gaming PC has an RTX 4090."

Memory B:
"User's gaming PC has 64 GB of RAM."

Relationship:
complementary

Memory A:
"User's gaming PC has an RTX 4090."

Memory B:
"User's gaming PC has an RTX 5090."

Relationship:
conflict

Memory A:
"User wants the media server installed in the server rack."

Memory B:
"User plans to move the media server into the same rack as
Freya's AI hardware."

Relationship:
duplicate

Also propose a semantic key ONLY when both memories describe
the same underlying property.

If they do not share one property, use null for
suggested_key.

Provide a short factual reason.

Do not decide which memory to keep.
Do not decide which memory is newer or more accurate unless
that information is explicitly contained in the memories.
Do not invent information.

Return ONLY valid JSON in this format:

{{
    "relationship": "duplicate",
    "reason": "Both memories describe the same media server location plan.",
    "suggested_key": "media_server_location"
}}

Memory A:
ID: {memory_a["id"]}
Type: {memory_a["type"]}
Key: {memory_a["key"]}
Content: {memory_a["content"]}

Memory B:
ID: {memory_b["id"]}
Type: {memory_b["type"]}
Key: {memory_b["key"]}
Content: {memory_b["content"]}
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        format="json",
    )

    result = response[
        "message"
    ]["content"].strip()

    try:
        data = json.loads(
            result
        )
    except json.JSONDecodeError:
        return {
            "relationship": "uncertain",
            "reason": (
                "The memory analyzer returned "
                "an invalid response."
            ),
            "suggested_key": None,
        }

    relationship = str(
        data.get(
            "relationship",
            "uncertain",
        )
    ).strip().lower()

    if (
        relationship
        not in ALLOWED_MEMORY_RELATIONSHIPS
    ):
        relationship = "uncertain"

    reason = str(
        data.get(
            "reason",
            "",
        )
    ).strip()

    if not reason:
        reason = (
            "No reliable explanation was "
            "provided."
        )

    suggested_key = data.get(
        "suggested_key"
    )

    if suggested_key is not None:
        suggested_key = _normalize_key(
            str(suggested_key)
        )

        if not suggested_key:
            suggested_key = None

    return {
        "relationship": relationship,
        "reason": reason,
        "suggested_key": suggested_key,
    }