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

    result = response["message"]["content"].strip()

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