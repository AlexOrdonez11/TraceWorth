"""Explicit administrator operations; never run as API startup side effects."""
from datetime import datetime, timedelta, timezone
import re
import sqlite3
from uuid import uuid4

from .security import password_hash
from .storage import StorageIntegrityError


def bootstrap_owner(database, email, account_name, password):
    email, account_name = email.strip().lower(), account_name.strip()
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or len(email) > 254:
        raise ValueError('A valid email is required')
    if not account_name or len(account_name) > 120 or not 12 <= len(password) <= 256:
        raise ValueError('Account name must be 1–120 characters; password must be 12–256 characters')
    if not database.ready():
        raise RuntimeError('Run migrations before bootstrap')
    account_id, user_id = str(uuid4()), str(uuid4())
    hashed = password_hash(password)
    try:
        with database.connect() as db:
            db.execute('INSERT INTO accounts VALUES(?,?,?)', (account_id, account_name, datetime.now(timezone.utc).isoformat()))
            db.execute('INSERT INTO users VALUES(?,?,?,?)', (user_id, account_id, email, hashed))
    except (sqlite3.IntegrityError, StorageIntegrityError) as exc:
        raise ValueError('Owner already exists; bootstrap never resets an existing password') from exc
    return {'account_id': account_id, 'user_id': user_id}


def retain(database, days=30, batch_size=1000):
    """Delete one bounded batch by server receipt time; scheduling is external."""
    if not 1 <= days <= 36600 or not 1 <= batch_size <= 10000:
        raise ValueError('Retention days or batch size outside allowed bounds')
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with database.connect() as db:
        deleted = db.execute('DELETE FROM events WHERE (account_id,application_id,event_id) IN (SELECT account_id,application_id,event_id FROM events WHERE received_at<? ORDER BY received_at LIMIT ?)', (cutoff, batch_size)).rowcount
    return {'deleted_events': deleted, 'cutoff': cutoff, 'batch_size': batch_size,
            'more_may_remain': deleted == batch_size}


def provision_runtime_role(database, username, password):
    """Provision a dedicated least-privilege login in this dedicated app database."""
    if not database.postgres:
        raise ValueError('Runtime role provisioning requires PostgreSQL')
    if not re.fullmatch(r'[a-z_][a-z0-9_]{0,62}', username) or username.startswith('pg_') or username == 'postgres':
        raise ValueError('Runtime role must be a nonreserved lowercase SQL identifier')
    if not 20 <= len(password) <= 256:
        raise ValueError('Runtime database password must be 20–256 characters')
    from psycopg import sql
    with database.connect() as connection:
        db = connection.raw
        identity = db.execute('SELECT current_user AS owner,current_database() AS name').fetchone()
        if username == identity['owner']:
            raise ValueError('Runtime role must differ from administrator')
        existing = db.execute('SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=%s', (username,)).fetchone()
        if existing:
            # Refuse roles already owning objects or inheriting memberships.
            owned = db.execute('SELECT 1 FROM pg_class WHERE relowner=(SELECT oid FROM pg_roles WHERE rolname=%s) LIMIT 1', (username,)).fetchone()
            membership = db.execute('SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=%s) LIMIT 1', (username,)).fetchone()
            owned_database = db.execute('SELECT 1 FROM pg_database WHERE datdba=(SELECT oid FROM pg_roles WHERE rolname=%s) LIMIT 1', (username,)).fetchone()
            if owned or membership or owned_database or any(existing[field] for field in ('rolsuper', 'rolcreatedb', 'rolcreaterole', 'rolreplication', 'rolbypassrls')):
                raise ValueError('Existing role has ownership or memberships; review manually')
        verb = 'ALTER' if existing else 'CREATE'
        # Send a SCRAM verifier rather than plaintext in administrative SQL.
        verifier = db.pgconn.encrypt_password(password.encode('utf-8'), username.encode('utf-8'), b'scram-sha-256').decode('ascii')
        # New roles default to no superuser, replication or RLS bypass powers.
        # Existing privileged roles were rejected above. Do not ALTER those
        # protected flags: an RDS administrator is not a PostgreSQL superuser.
        db.execute(sql.SQL(verb + ' ROLE {} WITH LOGIN NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD {}').format(sql.Identifier(username), sql.Literal(verifier)))
        db.execute(sql.SQL('REVOKE ALL ON DATABASE {} FROM {}').format(sql.Identifier(identity['name']), sql.Identifier(username)))
        db.execute(sql.SQL('REVOKE TEMP ON DATABASE {} FROM PUBLIC').format(sql.Identifier(identity['name'])))
        db.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(identity['name']), sql.Identifier(username)))
        db.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
        db.execute(sql.SQL('REVOKE ALL ON SCHEMA public FROM {}').format(sql.Identifier(username)))
        db.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(sql.Identifier(username)))
        db.execute(sql.SQL('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {}').format(sql.Identifier(username)))
        for table in ('accounts', 'users', 'sessions', 'applications', 'api_keys', 'events'):
            db.execute(sql.SQL('GRANT SELECT,INSERT,UPDATE,DELETE ON TABLE {} TO {}').format(sql.Identifier(table), sql.Identifier(username)))
        db.execute(sql.SQL('GRANT SELECT ON TABLE schema_migrations TO {}').format(sql.Identifier(username)))
    return {'runtime_role': username, 'status': 'provisioned'}
