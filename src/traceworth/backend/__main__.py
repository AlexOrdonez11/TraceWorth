"""Loopback development server and explicit container/admin commands."""
import argparse
import getpass
import json
import os
import sys
import uvicorn
from .app import create_app
from .settings import Settings
from .storage import Database
from .management import bootstrap_owner, provision_runtime_role, retain


def main(argv=None):
    parser = argparse.ArgumentParser(description='TraceWorth API and explicit database administration.')
    parser.add_argument('command', nargs='?', default='serve-local', choices=['serve-local', 'serve-container', 'migrate', 'bootstrap-owner', 'provision-runtime-role', 'retain'])
    parser.add_argument('--port', type=int, default=18766)
    parser.add_argument('--database', default='local-data/traceworth.db')
    parser.add_argument('--allowed-origin', action='append')
    parser.add_argument('--email')
    parser.add_argument('--account-name')
    secret = parser.add_mutually_exclusive_group()
    secret.add_argument('--password-stdin', action='store_true')
    secret.add_argument('--password-env', action='store_true', help='Read TRACEWORTH_BOOTSTRAP_PASSWORD; never pass the value as an argument')
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--batch-size', type=int, default=1000)
    args = parser.parse_args(argv)
    database = None
    try:
        if args.command == 'serve-local':
            if not 1 <= args.port <= 65535:
                parser.error('port must be between 1 and 65535')
            uvicorn.run(create_app(args.database, args.allowed_origin), host='127.0.0.1', port=args.port, proxy_headers=False)
            return 0
        settings = Settings.from_env()
        if args.command == 'serve-container':
            app = create_app(allowed_origins=settings.allowed_origins or None,
                             database_url=settings.database, cloud_mode=settings.cloud_mode,
                             metrics_max_events=settings.metrics_max_events,
                             metrics_window_days=settings.metrics_window_days, pool_max=settings.pool_max)
            # Forwarded client IP headers are intentionally ignored. Network rules
            # restrict ingress, and Secure cookies are explicit in cloud mode.
            uvicorn.run(app, host='0.0.0.0', port=settings.port, proxy_headers=False, access_log=False)
            return 0
        database = Database(settings.database, auto_migrate=False, pool_max=settings.pool_max)
        if args.command == 'migrate':
            result = {'schema_version': database.migrate()}
        elif args.command == 'bootstrap-owner':
            if not args.email or not args.account_name:
                parser.error('bootstrap-owner requires --email and --account-name')
            if args.password_env:
                password = os.environ.get('TRACEWORTH_BOOTSTRAP_PASSWORD', '')
            elif args.password_stdin:
                password = sys.stdin.readline().rstrip('\r\n')
            else:
                password = getpass.getpass('New owner password: ')
            result = bootstrap_owner(database, args.email, args.account_name, password)
        elif args.command == 'provision-runtime-role':
            result = provision_runtime_role(database, os.environ.get('TRACEWORTH_RUNTIME_DB_USER', ''), os.environ.get('TRACEWORTH_RUNTIME_DB_PASSWORD', ''))
        else:
            result = retain(database, args.days, args.batch_size)
        print(json.dumps(result))
        return 0
    except Exception as exc:
        # Driver exceptions can embed DSNs/credentials: do not print their detail.
        print(f'TraceWorth command failed ({type(exc).__name__}). Check configuration, connectivity, migration version, and input requirements.', file=sys.stderr)
        return 1
    finally:
        if database:
            database.close()


if __name__ == '__main__':
    raise SystemExit(main())
