"""SQLite storage. Account ownership is explicit on every telemetry lookup."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

SCHEMA = '''
CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf_token TEXT NOT NULL, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS applications(id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), name TEXT NOT NULL, slug TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(account_id,slug), UNIQUE(account_id,id));
CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY, account_id TEXT NOT NULL, application_id TEXT NOT NULL, name TEXT NOT NULL, prefix TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL, created_at TEXT NOT NULL, revoked_at TEXT, FOREIGN KEY(account_id,application_id) REFERENCES applications(account_id,id));
CREATE TABLE IF NOT EXISTS events(account_id TEXT NOT NULL, application_id TEXT NOT NULL, event_id TEXT NOT NULL, payload TEXT NOT NULL, received_at TEXT NOT NULL, PRIMARY KEY(account_id,application_id,event_id), FOREIGN KEY(account_id,application_id) REFERENCES applications(account_id,id));
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
'''

class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()
