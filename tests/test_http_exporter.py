"""HTTP exporter behavior against a real local HTTP listener."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from threading import Thread
import time
import unittest
from urllib.error import HTTPError

from traceworth import HttpExporter, TraceWorth


@contextmanager
def receiver(response=None, status=200, headers=None, delay=0):
    received = []
    response = {'accepted': 1, 'duplicates': 0} if response is None else response

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            received.append({'path': self.path, 'headers': dict(self.headers), 'body': json.loads(body)})
            if delay:
                time.sleep(delay)
            body = json.dumps(response).encode()
            try:
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/api/events', received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class HttpExporterAcceptanceTests(unittest.TestCase):
    def test_sends_single_event_envelope_and_bearer_header(self):
        event = {'event_id': 'fixture', 'name': 'operation'}
        with receiver() as (endpoint, received):
            exporter = HttpExporter(endpoint, 'tw_test_secret')
            exporter(event)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['path'], '/api/events')
        self.assertEqual(received[0]['body'], {'events': [event]})
        self.assertEqual(received[0]['headers']['Authorization'], 'Bearer tw_test_secret')
        self.assertEqual(received[0]['headers']['Content-Type'], 'application/json')
        self.assertNotIn('tw_test_secret', repr(exporter))
        self.assertNotIn('tw_test_secret', str(exporter))

    def test_idempotent_duplicate_acknowledgement_is_success(self):
        with receiver({'accepted': 0, 'duplicates': 1}) as (endpoint, received):
            HttpExporter(endpoint, 'test-token')({'event_id': 'already-sent'})
        self.assertEqual(len(received), 1)

    def test_invalid_acknowledgements_raise(self):
        for response in [{}, [], {'accepted': True, 'duplicates': 0},
                         {'accepted': 0, 'duplicates': 0}, {'accepted': 2, 'duplicates': 0},
                         {'accepted': -1, 'duplicates': 2}]:
            with self.subTest(response=response):
                with receiver(response) as (endpoint, _):
                    with self.assertRaises(ValueError):
                        HttpExporter(endpoint, 'test-token')({})

    def test_redirect_does_not_forward_ingestion_credentials(self):
        with receiver() as (destination, forwarded):
            with receiver(status=307, headers={'Location': destination}) as (endpoint, received):
                with self.assertRaises(HTTPError) as failure:
                    HttpExporter(endpoint, 'sensitive-api-key')({})
                self.assertTrue(failure.exception.closed)
        self.assertEqual(len(received), 1)
        self.assertEqual(forwarded, [])

    def test_http_failure_increments_sdk_diagnostics_without_breaking_workflow(self):
        with receiver({'error': 'unauthorized'}, status=401) as (endpoint, received):
            with TraceWorth('portable', HttpExporter(endpoint, 'revoked-token')) as sdk:
                @sdk.workflow('business-operation')
                def run():
                    return 42
                self.assertEqual(run(), 42)
        self.assertEqual(len(received), 2)
        self.assertEqual(sdk.diagnostics['export_errors'], 2)
        self.assertEqual(sdk.diagnostics['pending_events'], 0)

    def test_timeout_bounds_transport(self):
        with receiver(delay=0.3) as (endpoint, received):
            exporter = HttpExporter(endpoint, 'token', timeout=0.05)
            started = time.monotonic()
            with self.assertRaises((TimeoutError, OSError)):
                exporter({})
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 1.0)
        self.assertEqual(len(received), 1)

    def test_sdk_import_works_without_backend_or_site_packages(self):
        source = str(Path(__file__).resolve().parents[1] / 'src')
        script = "import sys; sys.path.insert(0, " + repr(source) + "); from traceworth import HttpExporter, TraceWorth; assert 'fastapi' not in sys.modules; assert 'traceworth.backend' not in sys.modules"
        result = subprocess.run([sys.executable, '-S', '-c', script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_configuration_rejects_insecure_or_malformed_credentials(self):
        for endpoint in ['http://example.com/api/events', 'ftp://localhost/path',
                         'https://user:pass@example.com/path', 'https://example.com/path?secret=value',
                         'https://example.com/path#fragment']:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    HttpExporter(endpoint, 'key')
        for timeout in [0, -1, True, float('inf'), float('nan')]:
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    HttpExporter('http://localhost/api/events', 'key', timeout=timeout)
        for key in ['', ' ', 'token\nheader', None]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    HttpExporter('http://localhost/api/events', key)


if __name__ == '__main__':
    unittest.main()
