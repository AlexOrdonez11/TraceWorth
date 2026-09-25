"""Environment configuration; cloud mode fails closed on TLS and origin settings."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

@dataclass(frozen=True)
class Settings:
    database: object = field(repr=False)
    cloud_mode: bool
    allowed_origins: list[str]
    port: int = 8000
    pool_max: int = 5
    metrics_max_events: int = 10000
    metrics_window_days: int = 30

    @classmethod
    def from_env(cls):
        mode = os.environ.get('TRACEWORTH_MODE', 'local')
        if mode not in {'local', 'cloud'}:
            raise ValueError('TRACEWORTH_MODE must be local or cloud')
        cloud = mode == 'cloud'
        origins = json.loads(os.environ.get('TRACEWORTH_ALLOWED_ORIGINS', '[]'))
        if not isinstance(origins, list) or any(not isinstance(value, str) for value in origins):
            raise ValueError('TRACEWORTH_ALLOWED_ORIGINS must be a JSON array')
        if cloud and (not origins or any(not origin.startswith('https://') for origin in origins)):
            raise ValueError('Cloud mode requires explicit HTTPS allowed origins')
        database = os.environ.get('TRACEWORTH_DATABASE_URL')
        if not database and os.environ.get('TRACEWORTH_DB_HOST'):
            database = {'host': os.environ['TRACEWORTH_DB_HOST'],
                        'dbname': os.environ.get('TRACEWORTH_DB_NAME', 'traceworth'),
                        'user': os.environ['TRACEWORTH_DB_USER'],
                        'password': os.environ['TRACEWORTH_DB_PASSWORD'],
                        'port': int(os.environ.get('TRACEWORTH_DB_PORT', '5432')),
                        'sslmode': os.environ.get('TRACEWORTH_DB_SSLMODE', 'verify-full' if cloud else 'disable')}
            root = os.environ.get('TRACEWORTH_DB_SSLROOTCERT')
            if root:
                database['sslrootcert'] = root
        if cloud:
            if isinstance(database, str):
                if urlsplit(database).scheme not in {'postgresql', 'postgres'}:
                    raise ValueError('Cloud mode requires PostgreSQL')
                params = parse_qs(urlsplit(database).query)
                if any(len(params.get(key, [])) != 1 for key in ('sslmode', 'sslrootcert')):
                    raise ValueError('Cloud database URL requires one explicit sslmode and sslrootcert')
                sslmode, root = params.get('sslmode', [''])[0], params.get('sslrootcert', [''])[0]
            elif isinstance(database, dict):
                sslmode, root = database.get('sslmode'), database.get('sslrootcert')
            else:
                raise ValueError('Cloud mode requires PostgreSQL credentials')
            if sslmode != 'verify-full' or not root or not Path(root).is_file():
                raise ValueError('Cloud PostgreSQL requires sslmode=verify-full and an existing sslrootcert file')
        values = {'port': int(os.environ.get('TRACEWORTH_PORT', '8000')),
                  'pool_max': int(os.environ.get('TRACEWORTH_DB_POOL_MAX', '5')),
                  'metrics_max_events': int(os.environ.get('TRACEWORTH_METRICS_MAX_EVENTS', '10000')),
                  'metrics_window_days': int(os.environ.get('TRACEWORTH_METRICS_WINDOW_DAYS', '30'))}
        if not 1 <= values['port'] <= 65535 or not 1 <= values['pool_max'] <= 20 or not 1 <= values['metrics_max_events'] <= 100000 or not 1 <= values['metrics_window_days'] <= 366:
            raise ValueError('Port, pool, or metrics bounds are invalid')
        return cls(database=database or os.environ.get('TRACEWORTH_SQLITE_PATH', 'local-data/traceworth.db'),
                   cloud_mode=cloud, allowed_origins=origins, **values)
