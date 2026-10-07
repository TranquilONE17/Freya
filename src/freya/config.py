import os


MODEL = "gpt-oss:20b"
EMBEDDING_MODEL = "nomic-embed-text"

# File that receives audit-log checkpoints. It only makes tampering
# detectable when it is somewhere this machine cannot rewrite, such as
# an append-only share on another host. Unset means local checkpoints only.
AUDIT_CHECKPOINT_PATH = os.environ.get(
    "FREYA_AUDIT_CHECKPOINT_PATH"
) or None

SYSTEM_PROMPT = """
You are Freya, a locally hosted personal AI assistant.

Your name is Freya.

You are helpful, conversational, capable, and concise.
"""