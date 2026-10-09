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
    def test_malformed_event_is_rejected_and_connection_closed(self):
        class MalformedResponse(FakeResponse):
            def __init__(self):
                self.data = iter(b'[]\n')

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch.object(FakeConnection, "getresponse", return_value=MalformedResponse()),
              patch("local_coding_agent.select.select", return_value=([object()], [], []))):
            with self.assertRaises(ValueError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "task",
                    lambda: None)
        self.assertTrue(FakeConnection.instance.closed)

    def test_stalled_stream_checks_revocation(self):
        checks = 0

        def checkpoint():
            nonlocal checks
            checks += 1
            if checks == 3:
                raise PermissionError("revoked while idle")

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch("local_coding_agent.select.select", return_value=([], [], []))):
            with self.assertRaises(PermissionError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "task",
                    checkpoint)
        self.assertTrue(FakeConnection.instance.closed)

    def test_completed_stream_returns_joined_fragments(self):
        class CompleteResponse(FakeResponse):
            def __init__(self):
                self.data = iter(b'{"response":"hello ","done":false}\n{"response":"world","done":true}\n')

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch.object(FakeConnection, "getresponse", return_value=CompleteResponse()),
              patch("local_coding_agent.select.select", return_value=([object()], [], []))):
            result = ask_ollama_cancellable(
                "http://127.0.0.1:11434/api/generate", "mock", "task",
                lambda: None)
        self.assertEqual(result, "hello world")
        self.assertTrue(FakeConnection.instance.closed)

    def test_error_event_fails_closed(self):
        class ErrorResponse(FakeResponse):
            def __init__(self):
                self.data = iter(b'{"error":"internal failure","done":true}\n')

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch.object(FakeConnection, "getresponse", return_value=ErrorResponse()),
              patch("local_coding_agent.select.select", return_value=([object()], [], []))):
            with self.assertRaises(RuntimeError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "task",
                    lambda: None)
        self.assertTrue(FakeConnection.instance.closed)

    def test_nonlocal_endpoint_rejected_before_connection(self):
        with patch("local_coding_agent.http.client.HTTPConnection") as connection:
            with self.assertRaises(ValueError):
                ask_ollama_cancellable(
                    "http://remote.example:11434/api/generate", "mock", "task",
                    lambda: None)
        connection.assert_not_called()

    def test_stalled_stream_times_out(self):
        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch("local_coding_agent.select.select", return_value=([], [], [])),
              patch("local_coding_agent.time.monotonic", side_effect=[0, 1])):
            with self.assertRaises(TimeoutError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "task",
                    lambda: None, timeout=0.1)
        self.assertTrue(FakeConnection.instance.closed)

    def test_denied_before_connection(self):
        with patch("local_coding_agent.http.client.HTTPConnection") as connection:
            with self.assertRaises(PermissionError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "task",
                    lambda: (_ for _ in ()).throw(PermissionError("denied")))
        connection.assert_not_called()

    def test_invalid_fragment_type_fails_closed(self):
        class InvalidFragmentResponse(FakeResponse):
            def __init__(self):
                self.data = iter(b'{"response":123,"done":true}\n')

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch.object(FakeConnection, "getresponse", return_value=InvalidFragmentResponse()),
              patch("local_coding_agent.select.select", return_value=([object()], [], []))):
            with self.assertRaises(ValueError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "task",
                    lambda: None)
        self.assertTrue(FakeConnection.instance.closed)

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
