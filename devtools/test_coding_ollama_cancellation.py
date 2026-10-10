"""Cancellation closes a streamed Ollama connection before completion."""
import unittest
import json
import itertools
import threading
from unittest.mock import patch

from local_coding_agent import ask_ollama_cancellable


class FakeResponse:
    status = 200

    def __init__(self):
        self.closed = threading.Event()
        self.data = iter(b'{"response":"partial","done":false}\n')

    def read1(self, count):
        data = bytes(itertools.islice(self.data, count))
        if not data:
            self.closed.wait()
        return data

    def close(self):
        self.closed.set()


class FakeConnection:
    instance = None
    response_factory = FakeResponse

    def __init__(self, *args, **kwargs):
        self.sock = self
        self.closed = False
        self.response = None
        FakeConnection.instance = self

    def request(self, *args, **kwargs):
        pass

    def getresponse(self):
        self.response = self.response_factory()
        return self.response

    def settimeout(self, value):
        pass

    def shutdown(self, how):
        if self.response is not None:
            self.response.close()

    def close(self):
        self.closed = True
        self.shutdown(None)


class OllamaCancellationTests(unittest.TestCase):
    def test_reader_start_failure_preserves_error_and_closes_response(self):
        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch("local_coding_agent.threading.Thread.start",
                    side_effect=RuntimeError("Synthetic thread unavailable"))):
            with self.assertRaisesRegex(RuntimeError, "Synthetic thread unavailable"):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "test", lambda: None)
        self.assertTrue(FakeConnection.instance.closed)
        self.assertTrue(FakeConnection.instance.response.closed.is_set())

    def test_invalid_timeout_is_rejected_before_connection(self):
        for timeout in (0, -1, float("inf"), float("nan"), True):
            with self.subTest(timeout=timeout):
                with patch("local_coding_agent.http.client.HTTPConnection") as connection:
                    with self.assertRaises(ValueError):
                        ask_ollama_cancellable(
                            "http://127.0.0.1:11434/api/generate", "mock", "test",
                            lambda: None, timeout=timeout)
                    connection.assert_not_called()

    def test_metadata_events_count_toward_response_byte_limit(self):
        event = json.dumps({"response": "", "done": False,
                            "metadata": "x" * 40}).encode() + b"\n"
        self.assertLess(len(event), 120)

        class MetadataResponse(FakeResponse):
            def __init__(self):
                self.closed = threading.Event()
                self.data = iter(event * 2 + b'{"response":"ok","done":true}\n')

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch.object(FakeConnection, "response_factory", MetadataResponse),
              patch("local_coding_agent.MAX_RESPONSE_BYTES", 120)):
            with self.assertRaises(ValueError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "synthetic",
                    lambda: None)
        self.assertTrue(FakeConnection.instance.closed)

    def test_malformed_event_is_rejected_and_connection_closed(self):
        class MalformedResponse(FakeResponse):
            def __init__(self):
                self.closed = threading.Event()
                self.data = iter(b'[]\n')

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch.object(FakeConnection, "response_factory", MalformedResponse)):
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

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection)):
            with self.assertRaises(PermissionError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "task",
                    checkpoint)
        self.assertTrue(FakeConnection.instance.closed)

    def test_completed_stream_returns_joined_fragments(self):
        class CompleteResponse(FakeResponse):
            def __init__(self):
                self.closed = threading.Event()
                self.data = iter(b'{"response":"hello ","done":false}\n{"response":"world","done":true}\n')

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch.object(FakeConnection, "response_factory", CompleteResponse)):
            result = ask_ollama_cancellable(
                "http://127.0.0.1:11434/api/generate", "mock", "task",
                lambda: None)
        self.assertEqual(result, "hello world")
        self.assertTrue(FakeConnection.instance.closed)

    def test_error_event_fails_closed(self):
        class ErrorResponse(FakeResponse):
            def __init__(self):
                self.closed = threading.Event()
                self.data = iter(b'{"error":"internal failure","done":true}\n')

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch.object(FakeConnection, "response_factory", ErrorResponse)):
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
                self.closed = threading.Event()
                self.data = iter(b'{"response":123,"done":true}\n')

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection),
              patch.object(FakeConnection, "response_factory", InvalidFragmentResponse)):
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

        with (patch("local_coding_agent.http.client.HTTPConnection", FakeConnection)):
            with self.assertRaises(PermissionError):
                ask_ollama_cancellable(
                    "http://127.0.0.1:11434/api/generate", "mock", "task",
                    checkpoint)
        self.assertTrue(FakeConnection.instance.closed)


if __name__ == "__main__":
    unittest.main()
