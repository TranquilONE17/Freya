import os


MODEL = "gpt-oss:20b"
EMBEDDING_MODEL = "nomic-embed-text"

# Context capacity is an explicit per-request model setting. These do
# not alter Ollama's system-wide settings or the owner's configuration.
CONTEXT_WINDOW_TOKENS = int(os.environ.get("FREYA_CONTEXT_WINDOW_TOKENS", "16384"))
CONTEXT_OUTPUT_TOKENS = int(os.environ.get("FREYA_CONTEXT_OUTPUT_TOKENS", "2048"))

# File that receives audit-log checkpoints. It only makes tampering
# detectable when it is somewhere this machine cannot rewrite, such as
# an append-only share on another host. Unset means local checkpoints only.
AUDIT_CHECKPOINT_PATH = os.environ.get(
    "FREYA_AUDIT_CHECKPOINT_PATH"
) or None

# Whether Freya opens her window when she starts. Set FREYA_WINDOW=0 to
# start with the console only; /window opens it later.
OPEN_WINDOW = os.environ.get("FREYA_WINDOW", "1") != "0"

# Program that starts ComfyUI when an image is requested and it is not
# running. Unset means the standard Comfy Desktop install, if present.
COMFYUI_COMMAND = os.environ.get(
    "FREYA_COMFYUI_COMMAND"
) or None

# LibreHardwareMonitor's web server on this machine, which supplies
# temperatures, fan speeds, and other sensor readings.
SENSOR_URL = os.environ.get(
    "FREYA_SENSOR_URL"
) or "http://127.0.0.1:8085/data.json"

SYSTEM_PROMPT = """
You are Freya, a locally hosted personal AI assistant.

Your name is Freya.

You are helpful, conversational, capable, and concise.
"""
