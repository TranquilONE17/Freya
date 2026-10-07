import os


MODEL = "gpt-oss:20b"
EMBEDDING_MODEL = "nomic-embed-text"

# File that receives audit-log checkpoints. It only makes tampering
# detectable when it is somewhere this machine cannot rewrite, such as
# an append-only share on another host. Unset means local checkpoints only.
AUDIT_CHECKPOINT_PATH = os.environ.get(
    "FREYA_AUDIT_CHECKPOINT_PATH"
) or None

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