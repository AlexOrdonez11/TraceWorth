"""Explicit Docker acceptance; disposable containers/network only, no AWS.

Build image first, then: python tests/container_smoke.py --image traceworth:test
Requires Docker and the local backend/test extras. No persistent user volumes.
"""
import argparse
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
from uuid import uuid4
import httpx
from traceworth import HttpExporter, TraceWorth


def docker(*args, check=True):
    result = subprocess.run(['docker', *args], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError('Docker operation failed: ' + ' '.join(args[:2]) + '\n' + result.stderr)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', required=True)
    parser.add_argument('--postgres-image', default='postgres:17-alpine')
    args = parser.parse_args()
    suffix = uuid4().hex[:10]
    network, postgres, api = ['tw-smoke-' + kind + '-' + suffix for kind in ['net', 'pg', 'api']]
    password, owner_password, runtime_password = [secrets.token_urlsafe(30) for _ in range(3)]
    with tempfile.TemporaryDirectory(prefix='traceworth-container-smoke-') as temporary:
        root = Path(temporary)
        admin_env = root / 'admin.env'
        runtime_env = root / 'runtime.env'
        pg_env = root / 'postgres.env'
        pg_env.write_text(f'POSTGRES_USER=admin\nPOSTGRES_PASSWORD={password}\nPOSTGRES_DB=traceworth\n')
        common = f'TRACEWORTH_MODE=local\nTRACEWORTH_DB_HOST={postgres}\nTRACEWORTH_DB_NAME=traceworth\nTRACEWORTH_DB_SSLMODE=disable\n'
        admin_env.write_text(common + f'TRACEWORTH_DB_USER=admin\nTRACEWORTH_DB_PASSWORD={password}\nTRACEWORTH_BOOTSTRAP_PASSWORD={owner_password}\nTRACEWORTH_RUNTIME_DB_USER=runtime\nTRACEWORTH_RUNTIME_DB_PASSWORD={runtime_password}\n')
        runtime_env.write_text(common + f'TRACEWORTH_DB_USER=runtime\nTRACEWORTH_DB_PASSWORD={runtime_password}\n')
        docker('network', 'create', network)
        try:
            docker('run', '-d', '--name', postgres, '--network', network, '--env-file', str(pg_env), args.postgres_image)
            for _ in range(90):
                if 'accepting connections' in docker('exec', postgres, 'pg_isready', '-U', 'admin', check=False):
                    break
                time.sleep(1)
            else:
                raise AssertionError('PostgreSQL readiness timed out')
            for command in [('migrate',), ('migrate',), ('provision-runtime-role',),
                            ('bootstrap-owner', '--email', 'owner@example.test', '--account-name', 'Container smoke', '--password-env')]:
                docker('run', '--rm', '--network', network, '--env-file', str(admin_env), args.image, *command)
            user = json.loads(docker('image', 'inspect', args.image))[0]['Config']['User']
            assert user == '10001:10001', user
            docker('run', '-d', '--name', api, '--network', network, '--env-file', str(runtime_env),
                   '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m', '-p', '127.0.0.1::8000', args.image)
            address = docker('port', api, '8000/tcp').splitlines()[0]
            url = 'http://' + address
            def ready():
                for _ in range(60):
                    try:
                        if httpx.get(url + '/api/health/ready', timeout=2).status_code == 200:
                            return
                    except httpx.HTTPError:
                        pass
                    time.sleep(.5)
                raise AssertionError('API readiness timed out')
            ready()
            with httpx.Client(base_url=url) as client:
                login = client.post('/api/auth/login', json={'email': 'owner@example.test', 'password': owner_password})
                assert login.status_code == 200, login.status_code
                csrf = {'X-CSRF-Token': login.json()['csrf_token']}
                app = client.post('/api/applications', json={'name': 'SDK fixture', 'slug': 'container-sdk'}, headers=csrf)
                assert app.status_code == 201, app.status_code
                app_id = app.json()['application']['id']
                key = client.post(f'/api/applications/{app_id}/keys', json={'name': 'temporary key'}, headers=csrf)
                assert key.status_code == 201, key.status_code
                token = key.json()['token']
                with TraceWorth('container-sdk', HttpExporter(url + '/api/events', token)) as sdk:
                    with sdk.span('container-workflow', workflow=True):
                        sdk.record_usage('fixture', 'service', {'tokens': 11}, amount='0.02', currency='USD', cost_basis='estimated')
                        sdk.record_outcome('accepted', True)
                assert not any(sdk.diagnostics.values()), sdk.diagnostics
                report = client.get('/api/metrics').json()['report']
                assert report['input']['valid_events'] == 4, report['input']
                assert report['cohorts'][0]['costs'][0]['amount'] == '0.02'
                docker('restart', api)
                ready()
                assert client.get('/api/metrics').json()['report']['input']['valid_events'] == 4
                assert client.delete(f'/api/applications/{app_id}/keys/{key.json()["key"]["id"]}', headers=csrf).status_code == 204
                assert client.post('/api/events', json={'events': [{}]}, headers={'Authorization': 'Bearer ' + token}).status_code == 401
            print('PASS: non-root/read-only container, explicit repeat migrations/bootstrap, runtime DB role, real SDK ingestion, persistence after restart, key revocation.')
        finally:
            docker('rm', '-f', api, postgres, check=False)
            docker('network', 'rm', network, check=False)


if __name__ == '__main__':
    main()
