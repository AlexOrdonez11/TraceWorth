"""Loopback-only local dashboard; no hosted services or external assets."""
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from .assessment import assess_file, _ingest

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
STATIC = Path(__file__).with_name("static")
ROUTES = {"/": ("index.html", "text/html"),
          "/dashboard": ("dashboard.html", "text/html"),
          "/dashboard/": ("dashboard.html", "text/html"),
          "/styles.css": ("styles.css", "text/css"),
          "/app.js": ("app.js", "text/javascript"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml")}


class LocalServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR can silently share another app's listening port.
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def create_server(events=None, host="127.0.0.1", port=8765):
    if host != "127.0.0.1":
        raise ValueError("The local dashboard must bind to 127.0.0.1")
    source_path = Path(events).resolve() if events is not None else None
    demo_report = None
    if source_path is None:
        from .cli import create_demo
        with tempfile.TemporaryDirectory(prefix="traceworth-web-") as directory:
            demo_path = Path(directory) / "events.jsonl"
            create_demo(demo_path)
            demo_report = assess_file(demo_path)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, format, *args):
            # Avoid echoing user-controlled URLs and telemetry into terminal logs.
            pass

        def send_body(self, status, body, content_type="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)

        def json_response(self, status, data):
            self.send_body(status, json.dumps(data, allow_nan=False).encode("utf-8"))

        def allowed(self):
            port = self.server.server_address[1]
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host", "").lower() not in hosts:
                self.json_response(403, {"error": "This server accepts local requests only."})
                return False
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://{name}" for name in hosts}:
                self.json_response(403, {"error": "Cross-origin requests are not allowed."})
                return False
            return True

        def envelope(self, report, kind, name):
            return {"report": report, "source": {"kind": kind, "name": name},
                    "loaded_at": datetime.now(timezone.utc).isoformat()}

        def do_GET(self):
            if not self.allowed():
                return
            path = urlsplit(self.path).path
            if path == "/api/report":
                try:
                    if source_path is None:
                        result = self.envelope(demo_report, "demo", "Synthetic demo")
                    else:
                        result = self.envelope(assess_file(source_path), "file", source_path.name)
                    self.json_response(200, result)
                except (OSError, ValueError) as exc:
                    self.json_response(400, {"error": f"Cannot read the configured event file ({type(exc).__name__}). Check the file and refresh."})
            elif path in ROUTES:
                name, mime = ROUTES[path]
                self.send_body(200, (STATIC / name).read_bytes(), mime)
            else:
                self.json_response(404, {"error": "Page not found."})

        def do_POST(self):
            if not self.allowed():
                return
            if urlsplit(self.path).path != "/api/assess":
                self.json_response(404, {"error": "Endpoint not found."})
                return
            if self.headers.get("Transfer-Encoding"):
                self.json_response(400, {"error": "Provide a fixed content length."})
                return
            try:
                size = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                size = -1
            if size < 0:
                self.json_response(411, {"error": "Content-Length is required."})
                return
            if size > MAX_UPLOAD_BYTES:
                self.json_response(413, {"error": "Choose a JSONL file no larger than 10 MiB."})
                return
            if self.headers.get("Content-Type", "").split(";")[0] not in ("text/plain", "application/x-ndjson", "application/json"):
                self.json_response(415, {"error": "Send a UTF-8 JSONL file as text/plain."})
                return
            try:
                data = self.rfile.read(size)
                if len(data) != size:
                    raise ValueError("Incomplete upload")
                def records():
                    for line, raw in enumerate(data.splitlines(), 1):
                        try:
                            value = json.loads(raw.decode("utf-8"))
                        except (ValueError, UnicodeError, RecursionError) as exc:
                            yield line, None, str(exc)
                        else:
                            yield line, value, None
                report = _ingest(records())
                self.json_response(200, self.envelope(report, "upload", "Imported JSONL"))
            except (ValueError, OSError) as exc:
                self.json_response(400, {"error": "Could not read this upload. Choose a UTF-8 JSONL file and try again."})

    return LocalServer((host, port), Handler)


def serve(events=None, port=8765):
    server = create_server(events, port=port)
    print(f"TraceWorth: http://127.0.0.1:{server.server_address[1]}", flush=True)
    print("Dashboard: /dashboard | Press Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
