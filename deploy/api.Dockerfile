# syntax=docker/dockerfile:1
# Адаптация AI Agent Capper backend/Dockerfile; источник — docs/sources/infra-reuse.md.
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

FROM base AS dependencies
WORKDIR /build
COPY backend/requirements.lock ./
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    python -m venv /opt/venv && \
    /opt/venv/bin/pip install --require-hashes -r requirements.lock && \
    /opt/venv/bin/pip check

FROM base AS runtime
RUN groupadd --gid 10001 pgweb && \
    useradd --uid 10001 --gid pgweb --home-dir /app --no-create-home \
    --shell /usr/sbin/nologin pgweb && \
    mkdir /downloads && chown pgweb:pgweb /downloads
COPY --from=dependencies /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY --chown=pgweb:pgweb backend/alembic.ini ./
COPY --chown=pgweb:pgweb backend/alembic ./alembic
COPY --chown=pgweb:pgweb backend/app ./app
RUN python -m compileall -q app alembic
# Хеш коммита сборки (deploy/deploy.sh); /api/health отвечает им, локально — dev
ARG PGWEB_VERSION=dev
ENV PGWEB_VERSION=$PGWEB_VERSION
USER pgweb
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--no-access-log", "--no-proxy-headers"]
