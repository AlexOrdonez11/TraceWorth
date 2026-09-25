"""Independent acceptance tests for authenticated ingestion and tenant isolation."""
from contextlib import closing
import copy
import json
from pathlib import Path
import sqlite3
import socket
from threading import Thread
import time
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import uvicorn
from traceworth import HttpExporter, TraceWorth
from traceworth.backend import create_app
from test_mvp_acceptance import span, usage, outcome

ORIGIN = 'http://localhost:5173'
PASSWORD = 'local-test-password-123!'


class BackendAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / 'backend.sqlite3'
        self.app = create_app(database_path=self.database, allowed_origins=[ORIGIN])
        self.alice = TestClient(self.app)
        self.bob = TestClient(self.app)
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(self.alice.close)
        self.addCleanup(self.bob.close)
        self.alice_auth = self.register(self.alice, 'alice@example.test', 'Alice company')
        self.bob_auth = self.register(self.bob, 'bob@example.test', 'Bob company')
        self.alice_csrf = {'X-CSRF-Token': self.alice_auth['csrf_token'], 'Origin': ORIGIN}
        self.bob_csrf = {'X-CSRF-Token': self.bob_auth['csrf_token'], 'Origin': ORIGIN}
        self.alice_app = self.create_application(self.alice, self.alice_csrf, 'Same application', 'portable')
        self.bob_app = self.create_application(self.bob, self.bob_csrf, 'Same application', 'portable')
        self.alice_key = self.create_key(self.alice, self.alice_csrf, self.alice_app['id'])
        self.bob_key = self.create_key(self.bob, self.bob_csrf, self.bob_app['id'])

    def register(self, client, email, name):
        response = client.post('/api/auth/register', json={'email': email, 'password': PASSWORD,
                                                         'account_name': name}, headers={'Origin': ORIGIN})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def create_application(self, client, headers, name, slug):
        response = client.post('/api/applications', json={'name': name, 'slug': slug}, headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()['application']

    def create_key(self, client, headers, application_id):
        response = client.post(f'/api/applications/{application_id}/keys', json={'name': 'SDK test key'}, headers=headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def ingest(self, key, events):
        return self.alice.post('/api/events', json={'events': events},
                               headers={'Authorization': 'Bearer ' + key['token']})

    def test_two_accounts_same_event_ids_are_independent(self):
        records = span()
        records.append(usage(records[0]['step_id'], '1'))
        first = self.ingest(self.alice_key, records)
        second = self.ingest(self.bob_key, records)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(first.json(), {'accepted': 3, 'duplicates': 0})
        self.assertEqual(second.json(), {'accepted': 3, 'duplicates': 0})
        alice = self.alice.get('/api/metrics').json()
        bob = self.bob.get('/api/metrics').json()
        self.assertEqual(alice['report']['input']['valid_events'], 3)
        self.assertEqual(bob['report']['input']['valid_events'], 3)
        self.assertEqual({a['id'] for a in alice['applications']}, {self.alice_app['id']})
        self.assertEqual({a['id'] for a in bob['applications']}, {self.bob_app['id']})

    def test_anonymous_and_ingestion_key_cannot_read_metrics(self):
        with closing(TestClient(self.app)) as anonymous:
            self.assertEqual(anonymous.get('/api/metrics').status_code, 401)
            self.assertEqual(anonymous.get('/api/applications').status_code, 401)
            self.assertEqual(anonymous.get('/api/metrics', headers={'Authorization': 'Bearer ' + self.alice_key['token']}).status_code, 401)
            self.assertEqual(anonymous.post('/api/events', json={'events': span()}).status_code, 401)

    def test_foreign_application_and_key_ids_do_not_grant_access(self):
        foreign_id = self.bob_app['id']
        for method, path, payload in [
                ('GET', f'/api/applications/{foreign_id}/keys', None),
                ('POST', f'/api/applications/{foreign_id}/keys', {'name': 'intruder'}),
                ('DELETE', f'/api/applications/{foreign_id}/keys/{self.bob_key["key"]["id"]}', None),
                ('GET', f'/api/metrics?application_id={foreign_id}', None)]:
            with self.subTest(method=method, path=path):
                response = self.alice.request(method, path, headers=self.alice_csrf, json=payload)
                self.assertEqual(response.status_code, 404, response.text)
        wrong_app_key = self.alice.delete(f'/api/applications/{self.alice_app["id"]}/keys/{self.bob_key["key"]["id"]}', headers=self.alice_csrf)
        self.assertEqual(wrong_app_key.status_code, 404)
        self.assertEqual(self.ingest(self.bob_key, span()).status_code, 200)

    def test_key_revocation_and_one_time_secret(self):
        listed = self.alice.get(f'/api/applications/{self.alice_app["id"]}/keys')
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn(self.alice_key['token'], listed.text)
        self.assertNotIn('token', listed.json()['keys'][0])
        revoked = self.alice.delete(f'/api/applications/{self.alice_app["id"]}/keys/{self.alice_key["key"]["id"]}', headers=self.alice_csrf)
        self.assertEqual(revoked.status_code, 204, revoked.text)
        self.assertEqual(self.ingest(self.alice_key, span()).status_code, 401)
        self.assertEqual(self.ingest(self.bob_key, span()).status_code, 200)

    def test_password_and_token_secrets_not_stored_plaintext(self):
        with closing(sqlite3.connect(self.database)) as db:
            dump = '\n'.join(db.iterdump())
            hashes = [row[0] for row in db.execute('SELECT password_hash FROM users')]
        self.assertEqual(len(set(hashes)), 2)
        self.assertTrue(all(value.startswith('scrypt$') for value in hashes))
        self.assertNotIn(PASSWORD, dump)
        self.assertNotIn(self.alice_key['token'], dump)
        self.assertNotIn(self.alice.cookies.get('traceworth_session'), dump)
        self.assertNotIn('password', self.alice.get('/api/auth/me').json()['user'])

    def test_logout_invalidates_server_session(self):
        stolen_cookie = self.alice.cookies.get('traceworth_session')
        response = self.alice.post('/api/auth/logout', headers=self.alice_csrf)
        self.assertIn(response.status_code, [200, 204], response.text)
        self.assertEqual(self.alice.get('/api/auth/me').status_code, 401)
        with closing(TestClient(self.app)) as replay:
            replay.cookies.set('traceworth_session', stolen_cookie)
            self.assertEqual(replay.get('/api/metrics').status_code, 401)
        self.assertEqual(self.bob.get('/api/auth/me').status_code, 200)

    def test_expired_session_is_rejected(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('UPDATE sessions SET expires_at = 0')
            db.commit()
        self.assertEqual(self.alice.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.alice.get('/api/metrics').status_code, 401)

    def test_csrf_and_origin_protect_session_mutations(self):
        payload = {'name': 'blocked', 'slug': 'blocked'}
        for headers in [{}, {'X-CSRF-Token': 'invalid'},
                        dict(self.alice_csrf, Origin='https://attacker.example'),
                        dict(self.alice_csrf, Origin='null')]:
            with self.subTest(headers=headers):
                response = self.alice.post('/api/applications', json=payload, headers=headers)
                self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(len(self.alice.get('/api/applications').json()['applications']), 1)
        response = self.alice.get('/api/metrics', headers={'Origin': 'https://attacker.example'})
        self.assertNotEqual(response.headers.get('access-control-allow-origin'), 'https://attacker.example')

    def test_non_ascii_csrf_is_rejected_without_server_error(self):
        response = self.alice.post('/api/applications', json={'name': 'blocked', 'slug': 'blocked'},
                                   headers=[(b'x-csrf-token', b'\xff')])
        self.assertEqual(response.status_code, 403, response.text)

    def test_replay_preserves_json_boolean_types_and_atomicity(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                original = outcome(True)
                if nested:
                    original['extra_context'] = {'flags': [True]}
                self.assertEqual(self.ingest(self.alice_key, [original]).status_code, 200)
                changed = copy.deepcopy(original)
                if nested:
                    changed['extra_context']['flags'][0] = 1
                else:
                    changed['value'] = 1
                count_before = self.alice.get('/api/metrics').json()['report']['input']['valid_events']
                response = self.ingest(self.alice_key, span() + [changed])
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], count_before)

    def test_request_size_limit_and_invalid_json_are_controlled(self):
        headers = {'Authorization': 'Bearer ' + self.alice_key['token'], 'Content-Type': 'application/json'}
        oversized = self.alice.post('/api/events', content=b' ' * (2 * 1024 * 1024 + 1), headers=headers)
        self.assertEqual(oversized.status_code, 413)
        malformed = self.alice.post('/api/events', content=b'{bad-json', headers=headers)
        self.assertEqual(malformed.status_code, 422)
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 0)

    def test_spoofed_app_and_tenant_fields_are_rejected_atomically(self):
        for field, value in [('application_id', 'other-app'), ('tenant_id', self.bob_auth['account']['id']),
                             ('account_id', self.bob_auth['account']['id'])]:
            with self.subTest(field=field):
                records = span()
                records[1][field] = value
                response = self.ingest(self.alice_key, records)
                self.assertIn(response.status_code, [400, 403, 422], response.text)
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 0)

    def test_replays_idempotent_and_conflicts_atomic(self):
        records = span()
        response = self.ingest(self.alice_key, records)
        self.assertEqual(response.status_code, 200)
        replay = self.ingest(self.alice_key, records)
        self.assertEqual(replay.json(), {'accepted': 0, 'duplicates': 2})
        conflicting = copy.deepcopy(records[0])
        conflicting['name'] = 'changed'
        new_record = usage(records[0]['step_id'])
        conflict = self.ingest(self.alice_key, [new_record, conflicting])
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 2)

    def test_malformed_and_oversized_batches_are_atomic(self):
        for payload in [{'events': [span()[0], {}]}, {'events': []}, {'events': 'invalid'},
                        {'events': [span()[0] for _ in range(501)]}]:
            with self.subTest(batch_type=type(payload['events']).__name__, length=len(payload['events'])):
                response = self.alice.post('/api/events', json=payload, headers={'Authorization': 'Bearer ' + self.alice_key['token']})
                self.assertIn(response.status_code, [400, 413, 422], response.text)
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 0)

    def test_same_batch_replay_and_conflicting_duplicate_are_atomic(self):
        record = span()[0]
        response = self.ingest(self.alice_key, [record, record])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {'accepted': 1, 'duplicates': 1})
        another = span()[0]
        altered = dict(another, name='inconsistent')
        response = self.ingest(self.alice_key, [another, altered])
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 1)

    def test_ingestion_key_is_scoped_to_application_not_just_account(self):
        second = self.create_application(self.alice, self.alice_csrf, 'Second application', 'second')
        second_key = self.create_key(self.alice, self.alice_csrf, second['id'])
        records = span()
        self.assertIn(self.ingest(second_key, records).status_code, [400, 403, 422])
        for record in records:
            record['application_id'] = 'second'
        self.assertEqual(self.ingest(second_key, records).status_code, 200)
        first_metrics = self.alice.get('/api/metrics', params={'application_id': self.alice_app['id']})
        second_metrics = self.alice.get('/api/metrics', params={'application_id': second['id']})
        self.assertEqual(first_metrics.json()['report']['input']['valid_events'], 0)
        self.assertEqual(second_metrics.json()['report']['input']['valid_events'], 2)

    def test_auth_rate_limit_blocks_repeated_password_attempts(self):
        with closing(TestClient(self.app)) as anonymous:
            statuses = [anonymous.post('/api/auth/login', json={'email': 'alice@example.test',
                          'password': 'invalid-password-123'}).status_code for _ in range(11)]
        self.assertIn(401, statuses)
        self.assertEqual(statuses[-1], 429)

    def test_sdk_http_export_reaches_persisted_account_metrics(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(self.app, log_level='error', lifespan='off'))
        thread = Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(server.started)
            exporter = HttpExporter(f'http://127.0.0.1:{port}/api/events', self.alice_key['token'])
            with TraceWorth('portable', exporter) as sdk:
                with sdk.span('real-http-workflow', workflow=True):
                    sdk.record_usage('fixture-vendor', 'fixture-model', {'tokens': 9},
                                     amount='0.03', currency='USD', cost_basis='estimated')
                    sdk.record_outcome('accepted', True)
            self.assertEqual(sdk.diagnostics, {'pending_events': 0, 'dropped_events': 0, 'export_errors': 0})
            report = self.alice.get('/api/metrics').json()['report']
            self.assertEqual(report['input']['valid_events'], 4)
            self.assertEqual(report['cohorts'][0]['summary']['accepted_workflows'], 1)
            self.assertEqual(report['cohorts'][0]['costs'][0]['amount'], '0.03')
            self.assertEqual(self.bob.get('/api/metrics').json()['report']['input']['valid_events'], 0)
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            listener.close()
        self.assertFalse(thread.is_alive())

    def test_oversized_event_rejects_entire_batch(self):
        records = span()
        records[1]['extra'] = 'x' * (64 * 1024)
        response = self.ingest(self.alice_key, records)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 0)

    def test_jsonb_incompatible_text_is_rejected_atomically(self):
        for invalid in ['name\x00hidden', 'name\ud800hidden']:
            records = span()
            records[1]['name'] = invalid
            response = self.alice.post('/api/events', content=json.dumps({'events': records}), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.alice_key['token']})
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 0)

    def test_metrics_byte_budget_is_explicit_and_bounded(self):
        records = span()
        records.append(usage(records[0]['step_id'], '0.2'))
        self.assertEqual(self.ingest(self.alice_key, records).status_code, 200)
        with patch('traceworth.backend.app.MAX_METRICS_BYTES', 1000):
            response = self.alice.get('/api/metrics')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body['scope']['truncated'])
        self.assertIn('byte_limit', body['scope']['truncation_reasons'])
        self.assertLessEqual(body['scope']['input_bytes'], 1000)
        self.assertLess(body['scope']['returned_events'], 3)
        for cohort in body['report']['cohorts']:
            self.assertTrue(all(cost['partial'] for cost in cohort['costs']))

    def test_extreme_metrics_date_returns_controlled_error(self):
        response = self.alice.get('/api/metrics', params={'until': '0001-01-01T00:00:00Z'})
        self.assertEqual(response.status_code, 422, response.text)

    def test_login_password_verification_and_session_cookie_flags(self):
        with closing(TestClient(self.app)) as login:
            wrong = login.post('/api/auth/login', json={'email': 'alice@example.test', 'password': 'wrong-password-123'})
            self.assertEqual(wrong.status_code, 401, wrong.text)
            valid = login.post('/api/auth/login', json={'email': 'ALICE@example.test', 'password': PASSWORD})
            self.assertEqual(valid.status_code, 200, valid.text)
            self.assertEqual(valid.json()['account']['id'], self.alice_auth['account']['id'])
            cookie = valid.headers['set-cookie'].lower()
            self.assertIn('httponly', cookie)
            self.assertIn('samesite=', cookie)
            self.assertNotIn(PASSWORD, valid.text)


if __name__ == '__main__':
    unittest.main()
