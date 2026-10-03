import ollama

from config import MODEL


def chat(messages):
    response = ollama.chat(
        model=MODEL,
        messages=messages,
    )

    return response["message"]["content"]


def evaluate_memory(user_input):
    prompt = f"""
You are the memory evaluator for a personal AI assistant named Freya.

Determine whether the user's message contains durable information
that would be useful to remember in future conversations.

Good memories include:
- Personal preferences
- Names and relationships
- Long-term goals
- Project decisions
- Hardware or system information
- Stable plans
- Important facts the user explicitly provides

Do NOT save:
- Ordinary questions
- Greetings
- Temporary conversational details
- General knowledge
- Commands
- Speculation
- Information stated by the assistant
- Things that are only useful for the current conversation

User message:
{user_input}

If there is useful durable information, respond with ONLY:

MEMORY: <concise standalone memory>

If there is nothing worth remembering, respond with ONLY:

NO_MEMORY
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )

    result = response["message"]["content"].strip()

    if result.startswith("MEMORY:"):
        memory = result[len("MEMORY:"):].strip()

        if memory:
            return memory

    return None