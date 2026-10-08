import http
import json
import queue
import secrets
import socket
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from importlib import resources

from websockets.datastructures import Headers
from websockets.http11 import Response
from websockets.sync.server import serve


DEFAULT_PORT = 8770

LOOPBACK = "127.0.0.1"

SESSION_COOKIE = "freya_session"

MAX_MESSAGE_BYTES = 64 * 1024
MAX_TEXT_LENGTH = 4000

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}

# The page may only load its own files and talk to this server.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "img-src 'self'; connect-src 'self'; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _response(status, body=b"", content_type="text/plain; charset=utf-8", extra=None):
    if isinstance(body, str):
        body = body.encode("utf-8")

    headers = Headers()
    headers["Content-Type"] = content_type
    headers["Content-Length"] = str(len(body))
    headers["Connection"] = "close"

    for name, value in SECURITY_HEADERS.items():
        headers[name] = value

    for name, value in (extra or {}).items():
        headers[name] = value

    status = http.HTTPStatus(status)

    return Response(status.value, status.phrase, headers, body)


class Gateway:
    """
    Serves Freya's window on this computer only.

    Pages and images are plain HTTP GETs; everything interactive goes
    over one WebSocket. It listens on the loopback address and accepts
    a request only when:

      - its Host header names this server (blocks DNS rebinding),
      - it carries the session cookie, which is handed out once in
        exchange for a single-use key that Freya puts in the address
        she opens, and
      - for the WebSocket, its Origin is this server (blocks other
        web pages from connecting).

    This is a first step towards the authenticated gateway in the
    architecture, not a substitute for it: anything running as the
    same Windows user could still read the key.
    """

    def __init__(self, bus, gallery, actions, port=DEFAULT_PORT):
        self._bus = bus
        self._gallery = gallery
        self._actions = actions
        self._requested_port = port

        self._lock = threading.Lock()
        self._keys = set()
        self._sessions = set()

        self._work = queue.Queue()
        self._server = None
        self._threads = []
        self.port = None

        # Which windows are connected, for knowing when the last one
        # has been closed.
        self._clients = 0
        self._no_clients_since = time.monotonic()
        self.ever_connected = False

    # -- lifecycle ---------------------------------------------------

    def start(self) -> None:
        listener = self._bind()
        self.port = listener.getsockname()[1]

        self._server = serve(
            self._handle_socket,
            sock=listener,
            process_request=self._process_request,
            origins=self._origins(),
            max_size=MAX_MESSAGE_BYTES,
        )

        for target, name in (
            (self._server.serve_forever, "FreyaGateway"),
            (self._run_work, "FreyaGatewayWork"),
        ):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)

    def _bind(self):
        for port in (self._requested_port, 0):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

            try:
                listener.bind((LOOPBACK, port))
            except OSError:
                listener.close()
                continue

            listener.listen()

            return listener

        raise RuntimeError("No free port for Freya's window.")

    def stop(self) -> None:
        self._work.put(None)

        if self._server is not None:
            self._server.shutdown()

    def _origins(self):
        return [
            f"http://{host}:{self.port}"
            for host in (LOOPBACK, "localhost")
        ]

    def _hosts(self):
        return {
            f"{host}:{self.port}"
            for host in (LOOPBACK, "localhost")
        }

    def new_window_url(self) -> str:
        """
        An address that opens the window once. The key in it is
        exchanged for a session cookie and then stops working.
        """
        key = secrets.token_urlsafe(32)

        with self._lock:
            self._keys.add(key)

        return f"http://{LOOPBACK}:{self.port}/open?key={key}"

    # -- HTTP --------------------------------------------------------

    def _has_session(self, request) -> bool:
        cookie = SimpleCookie()

        try:
            cookie.load(request.headers.get("Cookie", ""))
        except Exception:
            return False

        morsel = cookie.get(SESSION_COOKIE)

        if morsel is None:
            return False

        with self._lock:
            return any(
                secrets.compare_digest(morsel.value, session)
                for session in self._sessions
            )

    def _process_request(self, connection, request):
        if request.headers.get("Host", "") not in self._hosts():
            return _response(403, "Forbidden.")

        url = urllib.parse.urlsplit(request.path)

        if url.path == "/open":
            return self._open(url)

        if not self._has_session(request):
            return _response(
                403,
                "This is Freya's window. Open it from Freya "
                "(type /window in her console).",
            )

        if url.path == "/ws":
            # Continue with the WebSocket handshake.
            return None

        if url.path in STATIC_FILES:
            name, content_type = STATIC_FILES[url.path]
            body = (
                resources.files("freya.gateway")
                .joinpath("static", name)
                .read_bytes()
            )
            return _response(200, body, content_type)

        if url.path.startswith("/images/"):
            image = self._gallery.read(url.path[len("/images/"):])

            if image is not None:
                media_type, body = image
                return _response(200, body, media_type)

        return _response(404, "Not found.")

    def _open(self, url):
        key = urllib.parse.parse_qs(url.query).get("key", [""])[0]

        with self._lock:
            valid = any(
                secrets.compare_digest(key, known)
                for known in self._keys
            )

            if valid:
                self._keys.discard(key)
                session = secrets.token_urlsafe(32)
                self._sessions.add(session)

        if not valid:
            return _response(
                403,
                "That link has already been used. Type /window in "
                "Freya's console for a new one.",
            )

        return _response(
            302,
            extra={
                "Location": "/",
                "Set-Cookie": (
                    f"{SESSION_COOKIE}={session}; Path=/; HttpOnly; "
                    "SameSite=Strict"
                ),
            },
        )

    # -- WebSocket ---------------------------------------------------

    def idle_seconds(self):
        """
        How long there has been no window connected, or None while at
        least one is.
        """
        with self._lock:
            if self._clients:
                return None

            return time.monotonic() - self._no_clients_since

    def _handle_socket(self, websocket) -> None:
        def forward(event):
            websocket.send(json.dumps(event))

        with self._lock:
            self._clients += 1
            self.ever_connected = True

        try:
            websocket.send(
                json.dumps(
                    {
                        "type": "hello",
                        "history": self._bus.history(),
                        "images": self._gallery.list(),
                        "status": self._actions.status(),
                        "console": self._actions.console_history(),
                    }
                )
            )

            self._bus.subscribe(forward)

            for raw in websocket:
                self._handle_message(websocket, raw)
        except Exception:
            # The window closed or the connection broke.
            pass
        finally:
            self._bus.unsubscribe(forward)

            with self._lock:
                self._clients -= 1

                if not self._clients:
                    self._no_clients_since = time.monotonic()

    def _handle_message(self, websocket, raw) -> None:
        def reject(reason):
            websocket.send(json.dumps({"type": "error", "text": reason}))

        try:
            message = json.loads(raw)
        except (TypeError, ValueError):
            return reject("That message could not be read.")

        if not isinstance(message, dict):
            return reject("That message could not be read.")

        kind = message.get("type")

        if kind in ("say", "image", "command"):
            text = message.get("text")

            if not isinstance(text, str) or not text.strip():
                return reject("There was nothing to send.")

            if len(text) > MAX_TEXT_LENGTH:
                return reject(
                    f"That is longer than {MAX_TEXT_LENGTH} characters."
                )

            self._work.put((kind, text.strip()))
        elif kind == "mute":
            self._actions.set_muted(message.get("muted") is True)
        elif kind == "interrupt":
            self._actions.interrupt()
        elif kind == "status":
            websocket.send(
                json.dumps(
                    {"type": "status", "status": self._actions.status()}
                )
            )
        else:
            reject("Freya's window sent something she did not expect.")

    def _run_work(self) -> None:
        """
        Turns asked for from the window run here one after another, so
        a long reply never blocks the connection.
        """
        while True:
            job = self._work.get()

            if job is None:
                return

            kind, text = job

            try:
                if kind == "say":
                    self._actions.say(text)
                elif kind == "image":
                    self._actions.generate_image(text)
                else:
                    self._actions.run_command(text)
            except Exception as exc:
                self._bus.publish(
                    "notice",
                    text=f"That did not work: {exc}",
                )
