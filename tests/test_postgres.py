"""Opt-in real PostgreSQL parity: creates/drops only generated test databases.

Set TRACEWORTH_TEST_POSTGRES_DSN to a disposable PostgreSQL server whose role
can CREATE DATABASE. The database named in the URL is never cleared or altered.
"""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
import unittest

from fastapi.testclient import TestClient
try:
    import psycopg
    from psycopg import sql
except ImportError:
    psycopg = None

import test_backend_acceptance as base
from test_mvp_acceptance import span, usage
from traceworth.backend import create_app
from traceworth.backend.storage import Database
from traceworth.backend.management import bootstrap_owner, provision_runtime_role

POSTGRES_DSN = os.environ.get('TRACEWORTH_TEST_POSTGRES_DSN')


@unittest.skipUnless(POSTGRES_DSN and psycopg, 'Set TRACEWORTH_TEST_POSTGRES_DSN and install PostgreSQL extra')
class PostgreSQLAcceptanceTests(base.BackendAcceptanceTests):
    def setUp(self):
        self.role_name = None
        self.database_name = 'tw_acceptance_' + uuid4().hex
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(self.database_name)))
        self.addCleanup(self.drop_database)
        parsed = urlsplit(POSTGRES_DSN)
        self.dsn = urlunsplit(parsed._replace(path='/' + self.database_name))
        self.database = Database(self.dsn, auto_migrate=False)
        self.addCleanup(self.database.close)
        self.database.migrate()
        self.app = create_app(database_url=self.dsn, allowed_origins=[base.ORIGIN])
        self.addCleanup(self.app.state.database.close)
        self.alice = TestClient(self.app)
        self.bob = TestClient(self.app)
        self.addCleanup(self.alice.close)
        self.addCleanup(self.bob.close)
        self.alice_auth = self.register(self.alice, 'alice@example.test', 'Alice company')
        self.bob_auth = self.register(self.bob, 'bob@example.test', 'Bob company')
        self.alice_csrf = {'X-CSRF-Token': self.alice_auth['csrf_token'], 'Origin': base.ORIGIN}
        self.bob_csrf = {'X-CSRF-Token': self.bob_auth['csrf_token'], 'Origin': base.ORIGIN}
        self.alice_app = self.create_application(self.alice, self.alice_csrf, 'Same application', 'portable')
        self.bob_app = self.create_application(self.bob, self.bob_csrf, 'Same application', 'portable')
        self.alice_key = self.create_key(self.alice, self.alice_csrf, self.alice_app['id'])
        self.bob_key = self.create_key(self.bob, self.bob_csrf, self.bob_app['id'])

    def drop_database(self):
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(self.database_name)))
            if self.role_name:
                admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(self.role_name)))

    def test_password_and_token_secrets_not_stored_plaintext(self):
        with self.database.connect() as connection:
            hashes = [row['password_hash'] for row in connection.execute('SELECT password_hash FROM users').fetchall()]
            stored_keys = [row['token_hash'] for row in connection.execute('SELECT token_hash FROM api_keys').fetchall()]
            stored_sessions = [row['token_hash'] for row in connection.execute('SELECT token_hash FROM sessions').fetchall()]
        self.assertEqual(len(set(hashes)), 2)
        self.assertTrue(all(value.startswith('scrypt$') for value in hashes))
        self.assertNotIn(base.PASSWORD, str(hashes))
        self.assertNotIn(self.alice_key['token'], stored_keys)
        self.assertNotIn(self.alice.cookies.get('traceworth_session'), stored_sessions)

    def test_expired_session_is_rejected(self):
        with self.database.connect() as connection:
            connection.execute('UPDATE sessions SET expires_at = 0')
        self.assertEqual(self.alice.get('/api/auth/me').status_code, 401)
        self.assertEqual(self.alice.get('/api/metrics').status_code, 401)

    def test_cloud_registration_demo_and_secure_sessions(self):
        cloud = create_app(database_url=self.dsn, allowed_origins=['https://dashboard.example.test'], cloud_mode=True)
        self.addCleanup(cloud.state.database.close)
        with closing(TestClient(cloud, base_url='https://dashboard.example.test')) as client:
            config = client.get('/api/config').json()
            self.assertEqual(config['mode'], 'cloud')
            self.assertFalse(config['registration_enabled'])
            self.assertFalse(config['demo_enabled'])
            registration = client.post('/api/auth/register', json={'email': 'new@example.test', 'password': base.PASSWORD, 'account_name': 'blocked'})
            self.assertEqual(registration.status_code, 403)
            login = client.post('/api/auth/login', json={'email': 'alice@example.test', 'password': base.PASSWORD})
            self.assertEqual(login.status_code, 200, login.text)
            self.assertIn('secure', login.headers['set-cookie'].lower())
            denied = client.post('/api/applications/' + self.alice_app['id'] + '/demo', headers={'X-CSRF-Token': login.json()['csrf_token']})
            self.assertEqual(denied.status_code, 403)
            self.assertEqual(client.get('/api/metrics').json()['report']['input']['valid_events'], 0)

    def test_readiness_distinguishes_live_and_migration_state(self):
        self.assertEqual(self.alice.get('/api/health/live').status_code, 200)
        self.assertEqual(self.alice.get('/api/health/ready').status_code, 200)
        with self.database.connect() as connection:
            connection.execute('DELETE FROM schema_migrations WHERE version=2')
        self.assertEqual(self.alice.get('/api/health/live').status_code, 200)
        self.assertEqual(self.alice.get('/api/health/ready').status_code, 503)
        self.database.migrate()
        self.assertEqual(self.alice.get('/api/health/ready').status_code, 200)

    def test_metrics_limits_and_truncation_are_explicit(self):
        records = span()
        records += [usage(records[0]['step_id'], '1')]
        self.assertEqual(self.ingest(self.alice_key, records).status_code, 200)
        response = self.alice.get('/api/metrics', params={'limit': 2})
        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertTrue(report['scope']['truncated'])
        self.assertEqual(report['scope']['returned_events'], 2)
        self.assertEqual(report['scope']['time_basis'], 'received_at')
        self.assertTrue(all(cost['partial'] for cohort in report['report']['cohorts'] for cost in cohort['costs']))
        for params in [{'limit': 0}, {'limit': 100001}, {'since': '2026-01-01'},
                       {'since': '2026-01-01T00:00:00Z', 'until': '2026-12-01T00:00:00Z'}]:
            self.assertEqual(self.alice.get('/api/metrics', params=params).status_code, 422)

    def test_bootstrap_creates_owner_and_never_resets_existing_password(self):
        long_password = 'a' * 160
        bootstrap_owner(self.database, 'pilot@example.test', 'Pilot account', long_password)
        with self.assertRaises(ValueError):
            bootstrap_owner(self.database, 'pilot@example.test', 'Replacement', 'different-password-123')
        with closing(TestClient(self.app)) as client:
            response = client.post('/api/auth/login', json={'email': 'pilot@example.test', 'password': long_password})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['account']['name'], 'Pilot account')
            self.assertEqual(client.get('/api/metrics').json()['report']['input']['valid_events'], 0)

    def test_runtime_role_can_read_data_but_not_change_schema(self):
        self.role_name = 'tw_runtime_' + uuid4().hex
        password = 'runtime-test-password-' + uuid4().hex
        provision_runtime_role(self.database, self.role_name, password)
        parsed = urlsplit(self.dsn)
        runtime_dsn = urlunsplit(parsed._replace(netloc=f'{self.role_name}:{password}@{parsed.hostname}:{parsed.port}'))
        with psycopg.connect(runtime_dsn) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM accounts').fetchone()[0], 2)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(runtime_dsn) as connection:
                connection.execute('CREATE TABLE forbidden(id INTEGER)')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(runtime_dsn) as connection:
                connection.execute('DELETE FROM schema_migrations')
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(runtime_dsn) as connection:
                connection.execute('CREATE TEMP TABLE forbidden_temp(id INTEGER)')

    def test_runtime_role_refuses_existing_replication_privilege(self):
        self.role_name = 'tw_replication_' + uuid4().hex
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE ROLE {} REPLICATION').format(sql.Identifier(self.role_name)))
        with self.assertRaises(ValueError):
            provision_runtime_role(self.database, self.role_name, 'disposable-runtime-password')

    def test_runtime_role_provisioning_repeats_under_nonsuperuser_owner(self):
        owner = 'tw_owner_' + uuid4().hex
        runtime = 'tw_limited_' + uuid4().hex
        database_name = 'tw_role_' + uuid4().hex
        password = 'disposable-role-password-' + uuid4().hex
        def cleanup():
            with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
                admin.execute(sql.SQL('DROP DATABASE IF EXISTS {} WITH (FORCE)').format(sql.Identifier(database_name)))
                admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(runtime)))
                admin.execute(sql.SQL('DROP ROLE IF EXISTS {}').format(sql.Identifier(owner)))
        self.addCleanup(cleanup)
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN CREATEDB CREATEROLE PASSWORD {}').format(sql.Identifier(owner), sql.Literal(password)))
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(database_name), sql.Identifier(owner)))
        parsed = urlsplit(POSTGRES_DSN)
        owner_dsn = urlunsplit(parsed._replace(netloc=f'{owner}:{password}@{parsed.hostname}:{parsed.port}', path='/' + database_name))
        database = Database(owner_dsn, auto_migrate=False)
        self.addCleanup(database.close)
        database.migrate()
        provision_runtime_role(database, runtime, password)
        provision_runtime_role(database, runtime, password + '-rotated')
        runtime_dsn = urlunsplit(urlsplit(owner_dsn)._replace(netloc=f'{runtime}:{password}-rotated@{parsed.hostname}:{parsed.port}'))
        with psycopg.connect(runtime_dsn) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM accounts').fetchone()[0], 0)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with psycopg.connect(runtime_dsn) as connection:
                connection.execute('CREATE TABLE forbidden(id INTEGER)')

    def test_repeat_migration_retains_accounts_keys_and_telemetry(self):
        records = span()
        self.assertEqual(self.ingest(self.alice_key, records).status_code, 200)
        self.database.migrate()
        self.database.migrate()
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 2)
        self.assertEqual(self.ingest(self.alice_key, records).json(), {'accepted': 0, 'duplicates': 2})

    def test_concurrent_identical_ingestion_is_idempotent(self):
        records = span()
        def submit(_):
            with closing(TestClient(self.app)) as client:
                return client.post('/api/events', json={'events': records},
                                   headers={'Authorization': 'Bearer ' + self.alice_key['token']})
        with ThreadPoolExecutor(max_workers=4) as workers:
            responses = list(workers.map(submit, range(4)))
        self.assertEqual([r.status_code for r in responses], [200] * 4)
        self.assertEqual(sum(r.json()['accepted'] for r in responses), 2)
        self.assertEqual(sum(r.json()['duplicates'] for r in responses), 6)
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 2)

    def test_concurrent_conflicting_event_commits_only_one_payload(self):
        record = span()[0]
        def submit(name):
            with closing(TestClient(self.app)) as client:
                return client.post('/api/events', json={'events': [dict(record, name=name)]},
                                   headers={'Authorization': 'Bearer ' + self.alice_key['token']})
        with ThreadPoolExecutor(max_workers=2) as workers:
            responses = list(workers.map(submit, ['first-name', 'second-name']))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])
        self.assertEqual(self.alice.get('/api/metrics').json()['report']['input']['valid_events'], 1)


if __name__ == '__main__':
    unittest.main()
