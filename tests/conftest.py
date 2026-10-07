import pytest

from freya.core.model_runtime import configure_model_runtime


class FakeOllama:
    """
    Stands in for the ollama client so tests never need a running
    Ollama server.
    """

    def __init__(self):
        self.installed = ["gpt-oss:20b", "nomic-embed-text:latest"]
        self.reachable = True
        self.calls = []
        self.reply = "Hello from the fake model."
        self.fail_mid_stream = False

    def _check(self):
        if not self.reachable:
            raise ConnectionError("Failed to connect to Ollama.")

    def list(self):
        self._check()
        return {"models": [{"model": name} for name in self.installed]}

    def generate(self, model, **kwargs):
        self._check()
        self.calls.append(("generate", model, kwargs))
        return {"response": ""}

    def embed(self, model, input, **kwargs):
        self._check()
        self.calls.append(("embed", model, input))
        return {"embeddings": [[0.1, 0.2, 0.3]]}

    def chat(self, model, messages, stream=False, **kwargs):
        self._check()
        self.calls.append(("chat", model, messages, stream, kwargs))

        if not stream:
            return {"message": {"content": self.reply}}

        return self._stream()

    def _stream(self):
        words = self.reply.split(" ")
        for index, word in enumerate(words):
            if self.fail_mid_stream and index == 2:
                raise ConnectionError("Ollama went away.")
            yield {"message": {"content": word + " "}}
        yield {"message": {"content": ""}}


@pytest.fixture
def fake_ollama(monkeypatch):
    fake = FakeOllama()
    monkeypatch.setattr("freya.providers.model.ollama.ollama", fake)
    return fake


@pytest.fixture(autouse=True)
def reset_model_runtime():
    yield
    configure_model_runtime(None)
