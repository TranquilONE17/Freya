"""Cancellation closes a streamed Ollama connection before completion."""
import unittest
from unittest.mock import patch

from local_coding_agent import ask_ollama_cancellable


class FakeResponse:
    status = 200

    def __init__(self):
        self.data = iter(b'{"response":"partial","done":false}\n')

    def read(self, count):
        return bytes([next(self.data)])


class FakeConnection:
    instance = None

    def __init__(self, *args, **kwargs):
        self.sock = self
        self.closed = False
        FakeConnection.instance = self

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        return FakeResponse()

    def settimeout(self, value):
        pass

    def close(self):
        self.closed = True


class OllamaCancellationTests(unittest.TestCase):
    def test_revocation_closes_stream(self):
        checks = 0

        def checkpoint():
            nonlocal checks
            checks += 1
            if checks > 4:
                raise PermissionError("revoked")

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch("local_coding_agent.select.select", return_value=([object()], [], []))):
            with self.assertRaises(PermissionError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "task",
                    checkpoint)
        self.assertTrue(FakeConnection.instance.closed)


if __name__ == "__main__":
    unittest.main()
