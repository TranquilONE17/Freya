"""Real HTTP framing regressions using synthetic loopback responses only."""
import http.client
import http.server
import json
import threading
import time
import unittest
from unittest.mock import patch

from local_coding_agent import ask_ollama_cancellable

REAL_CONNECTION = http.client.HTTPConnection
ENDPOINT = "http://127.0.0.1:11434/api/generate"
BODY = (json.dumps({"response": "hello ", "done": False}) + "\n"
        + json.dumps({"response": "世界", "done": True}, ensure_ascii=False)
        + "\n").encode("utf-8")


class SyntheticServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        mode, body = self.server.mode, self.server.body
        if mode == "stall-headers":
            self.server.sent.set()
            self.connection.settimeout(2)
            try:
                if not self.connection.recv(1):
                    self.server.peer_closed.set()
            except OSError:
                pass
            self.close_connection = True
            return
        connection = b"close" if mode in ("close", "stall-close") else b"keep-alive"
        chunked = mode in ("chunked", "stall-chunk-header")
        framing = (b"Transfer-Encoding: chunked\r\n" if chunked else
                   f"Content-Length: {len(body)}\r\n".encode())
        headers = (b"HTTP/1.1 200 OK\r\nContent-Type: application/x-ndjson\r\n"
                   + framing + b"Connection: " + connection + b"\r\n\r\n")
        if mode.startswith("stall"):
            partial = b"1" if chunked else body[:5]
            self.connection.sendall(headers + partial)
            self.server.sent.set()
            self.connection.settimeout(2)
            try:
                if not self.connection.recv(1):
                    self.server.peer_closed.set()
            except OSError:
                pass
            self.close_connection = True
            return
        if chunked:
            # Split UTF-8 and NDJSON across HTTP chunks, all sent with headers.
            chunks = [body[index:index + 1] for index in range(len(body))]
            body = b"".join(b"1\r\n" + chunk + b"\r\n" for chunk in chunks) + b"0\r\n\r\n"
        self.connection.sendall(headers + body)
        self.close_connection = connection == b"close"


class OllamaHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = SyntheticServer(("127.0.0.1", 0), Handler)
        self.server.mode = "length"
        self.server.body = BODY
        self.server.sent = threading.Event()
        self.server.peer_closed = threading.Event()
        self.worker = threading.Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.worker.start()

        def connection(host, port, **kwargs):
            return REAL_CONNECTION("127.0.0.1", self.server.server_port, **kwargs)

        self.client = patch("local_coding_agent.http.client.HTTPConnection", connection)
        self.client.start()

    def tearDown(self):
        self.client.stop()
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=2)
        self.assertFalse(self.worker.is_alive())
        self.assertFalse(any(thread.name.startswith("freya-ollama-reader-")
                             for thread in threading.enumerate()),
                         "Request left a response reader running")

    def generate(self, checkpoint=lambda: None, timeout=2):
        return ask_ollama_cancellable(ENDPOINT, "synthetic", "test",
                                     checkpoint, timeout=timeout)

    def test_prefetched_content_length_keep_alive(self):
        self.assertEqual(self.generate(), "hello 世界")

    def test_content_length_connection_close(self):
        self.server.mode = "close"
        self.assertEqual(self.generate(), "hello 世界")

    def test_chunked_prefetched_body_and_split_utf8(self):
        self.server.mode = "chunked"
        self.assertEqual(self.generate(), "hello 世界")

    def cancel_stalled_response(self, mode):
        self.server.mode = mode
        checks = 0

        def checkpoint():
            nonlocal checks
            checks += 1
            if checks >= 4 and self.server.sent.is_set():
                raise PermissionError("Synthetic revocation")

        start = time.monotonic()
        with self.assertRaises(PermissionError):
            self.generate(checkpoint)
        self.assertLess(time.monotonic() - start, 1)
        self.assertTrue(self.server.peer_closed.wait(1), "Cancelled socket stayed open")

    def test_cancellation_of_stalled_keep_alive_body(self):
        self.cancel_stalled_response("stall")

    def test_cancellation_of_stalled_connection_close_body(self):
        self.cancel_stalled_response("stall-close")

    def test_cancellation_during_partial_chunk_header(self):
        self.cancel_stalled_response("stall-chunk-header")

    def test_idle_body_obeys_deadline_and_closes_socket(self):
        self.server.mode = "stall"
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.generate(timeout=0.25)
        self.assertLess(time.monotonic() - start, 1)
        self.assertTrue(self.server.peer_closed.wait(1))

    def test_header_wait_obeys_short_timeout(self):
        self.server.mode = "stall-headers"
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            self.generate(timeout=0.1)
        self.assertLess(time.monotonic() - start, 0.4)
        self.assertTrue(self.server.peer_closed.wait(1))

    def test_eof_without_done_is_rejected(self):
        self.server.mode = "close"
        self.server.body = b'{"response":"partial","done":false}\n'
        with self.assertRaisesRegex(RuntimeError, "without completion"):
            self.generate()

    def test_malformed_event_closes_reader(self):
        self.server.body = b'[]\n'
        with self.assertRaises(ValueError):
            self.generate()

    def test_metadata_is_included_in_body_size_limit(self):
        event = json.dumps({"response": "", "done": False,
                            "metadata": "x" * 40}).encode() + b"\n"
        self.assertLess(len(event), 120)
        self.server.body = event * 2 + b'{"response":"ok","done":true}\n'
        with patch("local_coding_agent.MAX_RESPONSE_BYTES", 120):
            with self.assertRaises(ValueError):
                self.generate()


if __name__ == "__main__":
    unittest.main()
