"""SQLite and pooled PostgreSQL storage with explicit ordered migrations."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

SCHEMA_VERSION = 2
SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf_token TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS applications(id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), name TEXT NOT NULL, slug TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(account_id,slug), UNIQUE(account_id,id));
CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY, account_id TEXT NOT NULL, application_id TEXT NOT NULL, name TEXT NOT NULL, prefix TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT, FOREIGN KEY(account_id,application_id) REFERENCES applications(account_id,id));
CREATE TABLE IF NOT EXISTS events(account_id TEXT NOT NULL, application_id TEXT NOT NULL, event_id TEXT NOT NULL, payload TEXT NOT NULL, received_at TEXT NOT NULL, PRIMARY KEY(account_id,application_id,event_id), FOREIGN KEY(account_id,application_id) REFERENCES applications(account_id,id));
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
'''
INDEXES = '''
CREATE INDEX IF NOT EXISTS events_account_received ON events(account_id,received_at,application_id,event_id);
CREATE INDEX IF NOT EXISTS events_application_received ON events(account_id,application_id,received_at,event_id);
CREATE INDEX IF NOT EXISTS events_retention_received ON events(received_at);
'''

class StorageIntegrityError(Exception):
    pass

class PostgresConnection:
    def __init__(self, connection):
        self.raw = connection

    def execute(self, sql, parameters=()):
        import psycopg
        from psycopg.types.json import Jsonb
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            return self.raw.execute('SELECT 1')
        if sql.lstrip().upper().startswith('INSERT INTO EVENTS'):
            parameters = list(parameters)
            parameters[3] = Jsonb(json.loads(parameters[3]))
        try:
            return self.raw.execute(sql.replace('?', '%s'), parameters)
        except psycopg.IntegrityError as exc:
            raise StorageIntegrityError('Database constraint rejected operation') from exc

class Database:
    def __init__(self, path, *, auto_migrate=None, pool_max=5):
        self.postgres = isinstance(path, dict) or str(path).startswith(('postgresql://', 'postgres://'))
        self.pool = None
        if self.postgres:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            kwargs = {'row_factory': dict_row, 'connect_timeout': 5,
                      'options': '-c statement_timeout=10000 -c lock_timeout=5000'}
            if isinstance(path, dict):
                kwargs.update(path)
                conninfo = ''
            else:
                conninfo = str(path)
            self.pool = ConnectionPool(conninfo, kwargs=kwargs, min_size=0, max_size=pool_max,
                                       timeout=5, max_waiting=20, open=True,
                                       check=ConnectionPool.check_connection)
        else:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as db:
                db.execute('PRAGMA journal_mode=WAL')
        if auto_migrate is True or (auto_migrate is None and not self.postgres):
            self.migrate()

    @contextmanager
    def connect(self):
        if self.postgres:
            with self.pool.connection() as connection:
                yield PostgresConnection(connection)
            return
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def migrate(self):
        with self.connect() as db:
            db.execute('SELECT pg_advisory_xact_lock(782341095)' if self.postgres else 'BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)')
            versions = {row['version'] for row in db.execute('SELECT version FROM schema_migrations').fetchall()}
            if versions - {1, 2}:
                raise RuntimeError('Database schema is newer than this application')
            schema = SCHEMA.replace('expires_at REAL', 'expires_at DOUBLE PRECISION').replace('payload TEXT', 'payload JSONB') if self.postgres else SCHEMA
            for version, commands in [(1, schema), (2, INDEXES)]:
                if version not in versions:
                    for statement in commands.split(';'):
                        if statement.strip():
                            db.execute(statement)
                    db.execute('INSERT INTO schema_migrations VALUES(?,?)', (version, datetime.now(timezone.utc).isoformat()))
        return SCHEMA_VERSION

    def ready(self):
        with self.connect() as db:
            versions = {row['version'] for row in db.execute('SELECT version FROM schema_migrations').fetchall()}
            return versions == {1, 2}

    def close(self):
        if self.pool:
            self.pool.close()
