FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS builder
WORKDIR /build
COPY pyproject.toml README.md ./
RUN python -c "import subprocess,tomllib; config=tomllib.load(open('pyproject.toml','rb')); extras=config['project']['optional-dependencies']; subprocess.run(['python','-m','pip','wheel','--no-cache-dir','--wheel-dir','/wheels',*config['build-system']['requires'],*extras['backend'],*extras['postgres']],check=True)"
COPY src ./src
RUN python -m pip wheel --no-cache-dir --no-deps --no-index --find-links=/wheels --wheel-dir /wheels .

FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TRACEWORTH_MODE=cloud TRACEWORTH_PORT=8000 TRACEWORTH_DB_SSLROOTCERT=/etc/ssl/certs/rds-global-bundle.pem
COPY --from=builder /wheels /wheels
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels 'traceworth[backend,postgres]' && rm -rf /wheels
# Official RDS trust bundle; checksum reviewed Sep 24 2026. Rotation requires review.
RUN python -c "import hashlib,pathlib,urllib.request; data=urllib.request.urlopen('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem',timeout=30).read(); assert hashlib.sha256(data).hexdigest()=='e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3'; pathlib.Path('/etc/ssl/certs/rds-global-bundle.pem').write_bytes(data)"
RUN groupadd --gid 10001 traceworth && useradd --uid 10001 --gid 10001 --no-create-home traceworth && mkdir -p /app/local-data && chown -R 10001:10001 /app
WORKDIR /app
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=8s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready',timeout=6)"
ENTRYPOINT ["python", "-m", "traceworth.backend"]
CMD ["serve-container"]
