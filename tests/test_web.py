"""Exercise real HTTP requests to an ephemeral loopback dashboard server."""
from contextlib import contextmanager
import http.client
import json
import socket
from pathlib import Path
import tempfile
from threading import Thread
import unittest

from traceworth.web import create_server
from test_mvp_acceptance import span, usage


@contextmanager
def running_server(events=None):
    server = create_server(events=events, host='127.0.0.1', port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def request(port, method='GET', path='/api/report', body=None, headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


class WebAcceptanceTests(unittest.TestCase):
    def test_landing_dashboard_and_default_demo_report(self):
        with running_server() as port:
            for path in ['/', '/dashboard']:
                status, headers, body = request(port, path=path)
                self.assertEqual(status, 200)
                self.assertIn('text/html', headers.get('Content-Type', ''))
                self.assertIn(b'TraceWorth', body)
            status, headers, body = request(port)
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload['source']['kind'], 'demo')
        self.assertTrue(payload['loaded_at'])
        self.assertGreaterEqual(len(payload['report']['cohorts']), 3)
        self.assertTrue(all(c['environment'] == 'synthetic-demo' for c in payload['report']['cohorts']))
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_configured_file_is_refreshed_each_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.jsonl'
            records = span()
            path.write_text(''.join(json.dumps(e) + '\n' for e in records), encoding='utf-8')
            with running_server(path) as port:
                status, _, body = request(port)
                initial = json.loads(body)
                self.assertEqual(status, 200)
                self.assertEqual(initial['source']['kind'], 'file')
                self.assertEqual(initial['report']['input']['valid_events'], 2)
                with path.open('a', encoding='utf-8') as output:
                    output.write(json.dumps(usage(records[0]['step_id'])) + '\n')
                status, _, body = request(port)
                refreshed = json.loads(body)
                self.assertEqual(status, 200)
                self.assertEqual(refreshed['report']['input']['valid_events'], 3)

    def test_upload_is_assessed_without_replacing_configured_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'events.jsonl'
            path.write_text('', encoding='utf-8')
            records = span()
            uploaded = ''.join(json.dumps(e) + '\n' for e in records).encode()
            with running_server(path) as port:
                status, _, body = request(port, 'POST', '/api/assess', uploaded,
                                          {'Content-Type': 'application/x-ndjson'})
                self.assertEqual(status, 200, body)
                payload = json.loads(body)
                self.assertEqual(payload['source']['kind'], 'upload')
                self.assertEqual(payload['report']['input']['valid_events'], 2)
                self.assertEqual(path.read_bytes(), b'')
                status, _, body = request(port)
                self.assertEqual(json.loads(body)['report']['input']['valid_events'], 0)

    def test_malformed_upload_reports_invalid_lines(self):
        with running_server() as port:
            status, _, body = request(port, 'POST', '/api/assess', b'{broken\n[]\n',
                                      {'Content-Type': 'application/x-ndjson'})
        self.assertEqual(status, 200, body)
        report = json.loads(body)['report']
        self.assertEqual(report['input']['invalid_lines'], 2)
        self.assertEqual(report['cohorts'], [])

    def test_empty_and_non_utf8_uploads_have_controlled_reports(self):
        with running_server() as port:
            for payload, invalid in [(b'', 0), (b'\xff\xfe\n', 1)]:
                with self.subTest(payload=payload):
                    status, _, body = request(port, 'POST', '/api/assess', payload,
                                              {'Content-Type': 'text/plain'})
                    self.assertEqual(status, 200, body)
                    report = json.loads(body)['report']
                    self.assertEqual(report['input']['invalid_lines'], invalid)
                    self.assertEqual(report['cohorts'], [])

    def test_deeply_nested_invalid_envelope_is_isolated(self):
        with running_server() as port:
            payload = b'[' * 1500 + b'0' + b']' * 1500 + b'\n'
            status, _, body = request(port, 'POST', '/api/assess', payload,
                                      {'Content-Type': 'text/plain'})
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)['report']['input']['invalid_lines'], 1)

    def test_unsupported_upload_type_and_chunked_upload_are_rejected(self):
        with running_server() as port:
            status, _, _ = request(port, 'POST', '/api/assess', b'', {'Content-Type': 'image/png'})
            self.assertEqual(status, 415)
            status, _, _ = request(port, 'POST', '/api/assess', b'',
                                   {'Content-Type': 'text/plain', 'Transfer-Encoding': 'chunked'})
            self.assertEqual(status, 400)

    def test_foreign_host_and_origin_are_rejected(self):
        with running_server() as port:
            for headers in [{'Host': 'attacker.example'}, {'Origin': 'https://attacker.example'},
                            {'Host': 'localhost.attacker.example'}, {'Origin': 'null'}]:
                with self.subTest(headers=headers):
                    status, response_headers, _ = request(port, headers=headers)
                    self.assertEqual(status, 403)
                    self.assertNotIn('Access-Control-Allow-Origin', response_headers)
            status, _, body = request(port, 'POST', '/api/assess', b'',
                                      {'Origin': f'http://127.0.0.1:{port}', 'Content-Type': 'application/x-ndjson'})
            self.assertEqual(status, 200, body)

    def test_traversal_and_arbitrary_paths_are_not_served(self):
        with running_server() as port:
            for path in ['/../pyproject.toml', '/%2e%2e/pyproject.toml', '/static/../../pyproject.toml',
                         '/api/file?path=C:/Windows/win.ini', '/src/traceworth/sdk.py']:
                with self.subTest(path=path):
                    status, _, body = request(port, path=path)
                    self.assertIn(status, [400, 403, 404])
                    self.assertNotIn(b'[build-system]', body)
                    self.assertNotIn(b'from __future__', body)

    def test_oversize_body_is_rejected_before_read(self):
        with running_server() as port:
            status, _, body = request(port, 'POST', '/api/assess', b'',
                                      {'Content-Length': str(10 * 1024 * 1024 + 1),
                                       'Content-Type': 'application/x-ndjson'})
        self.assertEqual(status, 413, body)

    def test_same_origin_cannot_be_faked_by_localhost_prefix(self):
        with running_server() as port:
            for origin in [f'http://127.0.0.1:{port}.attacker.example',
                           f'http://localhost.attacker.example:{port}',
                           f'http://127.0.0.1:{port + 1}', 'file://']:
                with self.subTest(origin=origin):
                    status, _, _ = request(port, 'POST', '/api/assess', b'',
                                            {'Origin': origin, 'Content-Type': 'application/x-ndjson'})
                    self.assertEqual(status, 403)

    def test_existing_listener_prevents_dashboard_port_overlap(self):
        # Reproduce another Windows app listening with SO_REUSEADDR enabled.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            occupied_port = listener.getsockname()[1]
            unexpected_server = None
            try:
                with self.assertRaises(OSError):
                    unexpected_server = create_server(port=occupied_port)
            finally:
                if unexpected_server is not None:
                    unexpected_server.server_close()

    def test_second_dashboard_cannot_share_first_dashboard_port(self):
        with running_server() as port:
            unexpected_server = None
            try:
                with self.assertRaises(OSError):
                    unexpected_server = create_server(port=port)
            finally:
                if unexpected_server is not None:
                    unexpected_server.server_close()
            status, _, body = request(port)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body)['source']['kind'], 'demo')

    def test_static_assets_are_served_with_expected_types(self):
        with running_server() as port:
            for path, content_type in [('/styles.css', 'text/css'), ('/app.js', 'text/javascript'),
                                       ('/favicon.svg', 'image/svg+xml')]:
                with self.subTest(path=path):
                    status, headers, body = request(port, path=path)
                    self.assertEqual(status, 200)
                    self.assertIn(content_type, headers['Content-Type'])
                    self.assertGreater(len(body), 20)

    def test_missing_configured_file_returns_controlled_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with running_server(Path(temporary) / 'missing.jsonl') as port:
                status, _, body = request(port)
        self.assertGreaterEqual(status, 400)
        self.assertIsInstance(json.loads(body), dict)
        self.assertNotIn(b'Traceback', body)


if __name__ == '__main__':
    unittest.main()
