"""Fail-closed cloud settings and non-destructive SQLite migration coverage."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from traceworth.backend.settings import Settings
from traceworth.backend.storage import Database, SCHEMA


class StagingConfigurationTests(unittest.TestCase):
    def test_cloud_requires_postgresql_full_tls_verification_and_https_origins(self):
        common = {'TRACEWORTH_MODE': 'cloud', 'TRACEWORTH_ALLOWED_ORIGINS': '["https://dashboard.example.test"]'}
        for change in [{}, {'TRACEWORTH_DATABASE_URL': 'sqlite:///local.db'},
                       {'TRACEWORTH_DATABASE_URL': 'postgresql://user:pass@localhost/db?sslmode=disable'},
                       {'TRACEWORTH_DATABASE_URL': 'postgresql://user:pass@localhost/db?sslmode=require'},
                       {'TRACEWORTH_ALLOWED_ORIGINS': '["http://localhost:5173"]'}]:
            with self.subTest(change=change), patch.dict(os.environ, dict(common, **change), clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env()

    def test_cloud_accepts_separate_credentials_only_with_explicit_certificate(self):
        with tempfile.TemporaryDirectory() as temporary:
            certificate = Path(temporary) / 'ca.pem'
            certificate.write_text('fixture file; configuration test only')
            environment = {'TRACEWORTH_MODE': 'cloud', 'TRACEWORTH_ALLOWED_ORIGINS': '["https://dashboard.example.test"]',
                           'TRACEWORTH_DB_HOST': 'db.example.test', 'TRACEWORTH_DB_USER': 'runtime',
                           'TRACEWORTH_DB_PASSWORD': 'test-secret', 'TRACEWORTH_DB_SSLROOTCERT': str(certificate)}
            with patch.dict(os.environ, environment, clear=True):
                settings = Settings.from_env()
            self.assertTrue(settings.cloud_mode)
            self.assertEqual(settings.database['sslmode'], 'verify-full')
            self.assertEqual(settings.pool_max, 5)

    def test_invalid_resource_bounds_fail_before_connecting(self):
        for name, value in [('TRACEWORTH_DB_POOL_MAX', '0'), ('TRACEWORTH_DB_POOL_MAX', '21'),
                            ('TRACEWORTH_METRICS_MAX_EVENTS', '0'), ('TRACEWORTH_PORT', '65536')]:
            with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env()

    def test_legacy_sqlite_schema_upgrades_and_preserves_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'legacy.db'
            connection = sqlite3.connect(path)
            try:
                connection.executescript(SCHEMA)
                connection.execute('INSERT INTO accounts VALUES(?,?,?)', ('legacy-account', 'Retained account', '2026-01-01'))
                connection.commit()
            finally:
                connection.close()
            database = Database(path)
            try:
                database.migrate()
                self.assertTrue(database.ready())
                with database.connect() as connection:
                    self.assertEqual(connection.execute('SELECT name FROM accounts').fetchone()['name'], 'Retained account')
                    self.assertEqual({r['version'] for r in connection.execute('SELECT version FROM schema_migrations')}, {1, 2})
            finally:
                database.close()


if __name__ == '__main__':
    unittest.main()
