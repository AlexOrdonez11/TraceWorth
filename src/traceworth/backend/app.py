"""FastAPI application for local account ownership and telemetry ingestion."""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ..assessment import assess_events
from ..sdk import TraceWorth
from ..validation import validate_event
from .security import AuthLimiter, digest, password_hash, verify_password
from .storage import Database

COOKIE = 'traceworth_session'
SESSION_SECONDS = 12 * 60 * 60
MAX_BODY_BYTES = 2 * 1024 * 1024
DEFAULT_ORIGINS = ['http://127.0.0.1:18767', 'http://localhost:18767', 'http://127.0.0.1:18766', 'http://localhost:18766']


def now_iso():
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Login(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


class Register(Login):
    account_name: str = Field(min_length=1, max_length=120)


class ApplicationInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$')


class KeyInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)


class EventBatch(StrictModel):
    events: list[dict] = Field(min_length=1, max_length=500)


class RequestGuard:
    """Reject untrusted browser origins and oversized bodies before parsing."""
    def __init__(self, app, allowed_origins):
        self.app = app
        self.origins = set(allowed_origins)

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        origin = headers.get(b'origin', b'').decode('latin1')
        if origin and origin not in self.origins:
            return await JSONResponse({'detail': 'Origin is not allowed'}, status_code=403)(scope, receive, send)
        if scope['method'] in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            length = headers.get(b'content-length')
            try:
                if length and (int(length) < 0 or int(length) > MAX_BODY_BYTES):
                    raise ValueError
            except ValueError:
                return await JSONResponse({'detail': 'Request body exceeds 2 MiB limit'}, status_code=413)(scope, receive, send)
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                body.extend(message.get('body', b''))
                if len(body) > MAX_BODY_BYTES:
                    return await JSONResponse({'detail': 'Request body exceeds 2 MiB limit'}, status_code=413)(scope, receive, send)
                if not message.get('more_body'):
                    break
            if body and headers.get(b'content-type', b'').split(b';')[0].strip().lower() != b'application/json':
                return await JSONResponse({'detail': 'Use application/json'}, status_code=415)(scope, receive, send)
            delivered = False
            original_receive = receive
            async def body_once():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await original_receive()
            return await self.app(scope, body_once, send)
        return await self.app(scope, receive, send)


def create_app(database_path: str | Path = 'local-data/traceworth.db', allowed_origins=None) -> FastAPI:
    origins = list(DEFAULT_ORIGINS if allowed_origins is None else allowed_origins)
    if any(origin == '*' or not re.fullmatch(r'https?://[^/]+', origin) for origin in origins):
        raise ValueError('allowed_origins must contain exact HTTP origins without paths or wildcards')
    database = Database(database_path)
    app = FastAPI(title='TraceWorth local API', version='0.1.0')
    app.state.database = database
    app.state.auth_limiter = AuthLimiter()
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                       allow_methods=['GET', 'POST', 'DELETE', 'OPTIONS'],
                       allow_headers=['Content-Type', 'Authorization', 'X-CSRF-Token'])
    app.add_middleware(RequestGuard, allowed_origins=origins)

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        # Never echo password or token input in validation errors.
        return JSONResponse({'detail': [{'loc': list(error['loc']), 'msg': error['msg'], 'type': error['type']} for error in exc.errors()]}, status_code=422)

    @app.middleware('http')
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def limited(request):
        if not app.state.auth_limiter.allow(request.client.host if request.client else 'unknown'):
            raise HTTPException(429, 'Too many sign-in attempts. Try again in a minute.', headers={'Retry-After': '60'})

    def identity(request, db, *, csrf=False):
        token = request.cookies.get(COOKIE, '')
        row = db.execute('SELECT s.token_hash,s.csrf_token,u.id AS user_id,u.email,u.account_id,a.name AS account_name FROM sessions s JOIN users u ON u.id=s.user_id JOIN accounts a ON a.id=u.account_id WHERE s.token_hash=? AND s.expires_at>?', (digest(token), time.time())).fetchone()
        if not row:
            raise HTTPException(401, 'Sign in to continue')
        if csrf and not hmac.compare_digest(request.headers.get('x-csrf-token', '').encode('utf-8'), row['csrf_token'].encode('utf-8')):
            raise HTTPException(403, 'Missing or invalid CSRF token')
        return row

    def auth_payload(row):
        return {'user': {'id': row['user_id'], 'email': row['email']},
                'account': {'id': row['account_id'], 'name': row['account_name']}, 'csrf_token': row['csrf_token']}

    def new_session(request, response, db, user_id):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
        old = request.cookies.get(COOKIE)
        if old:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (digest(old),))
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (digest(token), user_id, csrf, time.time() + SESSION_SECONDS))
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, samesite='strict', secure=request.url.scheme == 'https', path='/')
        row = db.execute('SELECT u.id AS user_id,u.email,u.account_id,a.name AS account_name FROM users u JOIN accounts a ON a.id=u.account_id WHERE u.id=?', (user_id,)).fetchone()
        return auth_payload(dict(row, csrf_token=csrf))

    def application(db, account_id, application_id):
        row = db.execute('SELECT id,name,slug,created_at FROM applications WHERE id=? AND account_id=?', (application_id, account_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Application not found')
        return dict(row)

    def application_list(db, account_id):
        return [dict(row) for row in db.execute('SELECT id,name,slug,created_at FROM applications WHERE account_id=? ORDER BY created_at,id', (account_id,))]

    def store_events(db, account_id, application_id, slug, events):
        payloads = []
        for index, event in enumerate(events):
            try:
                validate_event(event)
                if any(field in event for field in ('account_id', 'tenant_id', 'user_id')):
                    raise ValueError('Ownership fields are assigned by the API key, not event data')
                if event['application_id'] != slug:
                    raise ValueError('Event application_id must match the API key application slug')
                payload = json.dumps(event, sort_keys=True, separators=(',', ':'), allow_nan=False)
            except (ValueError, TypeError, OverflowError) as exc:
                raise HTTPException(422, f'Event {index}: {exc}') from exc
            payloads.append((event['event_id'], payload))
        accepted = duplicates = 0
        for event_id, payload in payloads:
            previous = db.execute('SELECT payload FROM events WHERE account_id=? AND application_id=? AND event_id=?', (account_id, application_id, event_id)).fetchone()
            if previous:
                if previous['payload'] != payload:
                    raise HTTPException(409, 'Conflicting event_id; entire batch rejected')
                duplicates += 1
            else:
                db.execute('INSERT INTO events VALUES(?,?,?,?,?)', (account_id, application_id, event_id, payload, now_iso()))
                accepted += 1
        return {'accepted': accepted, 'duplicates': duplicates}

    @app.get('/api/health')
    def health():
        return {'status': 'ok'}

    @app.post('/api/auth/register', status_code=201)
    def register(data: Register, request: Request, response: Response):
        limited(request)
        email = data.email.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or not data.account_name.strip():
            raise HTTPException(422, 'Enter a valid email and account name')
        account_id, user_id = str(uuid4()), str(uuid4())
        hashed = password_hash(data.password)
        try:
            with database.connect() as db:
                db.execute('INSERT INTO accounts VALUES(?,?,?)', (account_id, data.account_name.strip(), now_iso()))
                db.execute('INSERT INTO users VALUES(?,?,?,?)', (user_id, account_id, email, hashed))
                return new_session(request, response, db, user_id)
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, 'An account with this email already exists') from exc

    @app.post('/api/auth/login')
    def login(data: Login, request: Request, response: Response):
        limited(request)
        with database.connect() as db:
            row = db.execute('SELECT id,password_hash FROM users WHERE email=?', (data.email.strip().lower(),)).fetchone()
            if not row:
                password_hash(data.password)  # Avoid a cheap nonexistent-user path.
                raise HTTPException(401, 'Invalid email or password')
            if not verify_password(data.password, row['password_hash']):
                raise HTTPException(401, 'Invalid email or password')
            return new_session(request, response, db, row['id'])

    @app.get('/api/auth/me')
    def me(request: Request):
        with database.connect() as db:
            return auth_payload(identity(request, db))

    @app.post('/api/auth/logout', status_code=204)
    def logout(request: Request):
        with database.connect() as db:
            user = identity(request, db, csrf=True)
            db.execute('DELETE FROM sessions WHERE token_hash=?', (user['token_hash'],))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path='/', httponly=True, samesite='strict')
        return response

    @app.get('/api/applications')
    def applications(request: Request):
        with database.connect() as db:
            user = identity(request, db)
            return {'applications': application_list(db, user['account_id'])}

    @app.post('/api/applications', status_code=201)
    def add_application(data: ApplicationInput, request: Request):
        if not data.name.strip():
            raise HTTPException(422, 'Application name cannot be blank')
        try:
            with database.connect() as db:
                user = identity(request, db, csrf=True)
                app_id = str(uuid4())
                db.execute('INSERT INTO applications VALUES(?,?,?,?,?)', (app_id, user['account_id'], data.name.strip(), data.slug, now_iso()))
                return {'application': application(db, user['account_id'], app_id)}
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, 'This application slug already exists in your account') from exc

    @app.get('/api/applications/{application_id}/keys')
    def keys(application_id: str, request: Request):
        with database.connect() as db:
            user = identity(request, db)
            application(db, user['account_id'], application_id)
            return {'keys': [dict(row) for row in db.execute('SELECT id,name,prefix,created_at,revoked_at FROM api_keys WHERE account_id=? AND application_id=? ORDER BY created_at,id', (user['account_id'], application_id))]}

    @app.post('/api/applications/{application_id}/keys', status_code=201)
    def add_key(application_id: str, data: KeyInput, request: Request):
        if not data.name.strip():
            raise HTTPException(422, 'Key name cannot be blank')
        with database.connect() as db:
            user = identity(request, db, csrf=True)
            application(db, user['account_id'], application_id)
            key_id, token, created = str(uuid4()), 'tw_' + secrets.token_urlsafe(32), now_iso()
            prefix = token[:11]
            db.execute('INSERT INTO api_keys VALUES(?,?,?,?,?,?,?,NULL)', (key_id, user['account_id'], application_id, data.name.strip(), prefix, digest(token), created))
            return {'key': {'id': key_id, 'name': data.name.strip(), 'prefix': prefix, 'created_at': created, 'revoked_at': None}, 'token': token}

    @app.delete('/api/applications/{application_id}/keys/{key_id}', status_code=204)
    def revoke_key(application_id: str, key_id: str, request: Request):
        with database.connect() as db:
            user = identity(request, db, csrf=True)
            application(db, user['account_id'], application_id)
            result = db.execute('UPDATE api_keys SET revoked_at=COALESCE(revoked_at,?) WHERE id=? AND account_id=? AND application_id=?', (now_iso(), key_id, user['account_id'], application_id))
            if not result.rowcount:
                raise HTTPException(404, 'Key not found')
        return Response(status_code=204)

    @app.post('/api/events')
    def events(data: EventBatch, request: Request):
        authorization = request.headers.get('authorization', '')
        if not authorization.startswith('Bearer '):
            raise HTTPException(401, 'A scoped API key is required')
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            key = db.execute('SELECT k.account_id,k.application_id,a.slug FROM api_keys k JOIN applications a ON a.id=k.application_id AND a.account_id=k.account_id WHERE k.token_hash=? AND k.revoked_at IS NULL', (digest(authorization[7:]),)).fetchone()
            if not key:
                raise HTTPException(401, 'Invalid or revoked API key')
            return store_events(db, key['account_id'], key['application_id'], key['slug'], data.events)

    @app.post('/api/applications/{application_id}/demo')
    def demo(application_id: str, request: Request):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            user = identity(request, db, csrf=True)
            selected = application(db, user['account_id'], application_id)
            recorded = []
            with TraceWorth(selected['slug'], recorded.append, environment='synthetic-demo', configuration_id='synthetic-v1') as client:
                for attempt in (1, 2):
                    with client.span('synthetic_workflow', workflow=True) as workflow_id:
                        with client.span('synthetic_provider_call', attempt_number=attempt):
                            client.record_usage('synthetic', 'fixture-model', {'input_tokens': 100, 'output_tokens': 50}, amount='0.02', currency='USD', cost_basis='estimated', price_version='synthetic-v1')
                    client.record_outcome('accepted', attempt == 1, workflow_id=workflow_id)
                if not client.close() or any(client.diagnostics.values()):
                    raise HTTPException(500, 'Synthetic export failed')
            return store_events(db, user['account_id'], application_id, selected['slug'], recorded)

    @app.get('/api/metrics')
    def metrics(request: Request, application_id: str | None = None):
        with database.connect() as db:
            user = identity(request, db)
            apps = application_list(db, user['account_id'])
            if application_id:
                application(db, user['account_id'], application_id)
                records = db.execute('SELECT payload FROM events WHERE account_id=? AND application_id=? ORDER BY received_at,event_id', (user['account_id'], application_id)).fetchall()
            else:
                records = db.execute('SELECT payload FROM events WHERE account_id=? ORDER BY received_at,application_id,event_id', (user['account_id'],)).fetchall()
        # Replay identities are scoped to an application, including in account totals.
        by_application = {}
        for row in records:
            event = json.loads(row['payload'])
            by_application.setdefault(event['application_id'], []).append(event)
        report = assess_events([])
        for scoped_events in by_application.values():
            scoped = assess_events(scoped_events)
            report['cohorts'].extend(scoped['cohorts'])
            for field in ('valid_events', 'invalid_lines', 'duplicate_events'):
                report['input'][field] += scoped['input'][field]
            report['input']['errors'].extend(scoped['input']['errors'])
        return {'report': report, 'applications': apps, 'loaded_at': now_iso()}

    return app
