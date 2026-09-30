# syntax=docker/dockerfile:1
# FastAPI backend, CPU inference.
#   docker compose -f infra/compose/compose.yaml --profile cpu up -d --wait
#   docker build -f infra/docker/api.cpu.Dockerfile -t adaptive-kg-api:cpu .
#
# Note: on linux/amd64 the locked PyPI torch wheel also pulls the CUDA runtime wheels
# (nvidia-*-cu12), so this image is large there; CPU-only wheels are tracked in #79.

ARG PYTHON_IMAGE=python:3.12-slim
ARG POETRY_VERSION=2.4.1

# --- build stage: resolve the locked dependencies into /opt/venv -------------------------
FROM ${PYTHON_IMAGE} AS builder
ARG POETRY_VERSION
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Compilers for dependencies without a wheel on this platform (e.g. hdbscan on arm64)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Poetry gets its own virtualenv; the app dependencies go into the active /opt/venv
RUN python -m venv /opt/poetry \
    && /opt/poetry/bin/pip install "poetry==${POETRY_VERSION}" \
    && python -m venv /opt/venv

WORKDIR /app
COPY pyproject.toml poetry.lock README.md ./
RUN /opt/poetry/bin/poetry install --only main --no-root --no-ansi \
    && python -m spacy download en_core_web_sm

# --- runtime stage ------------------------------------------------------------------------
FROM ${PYTHON_IMAGE} AS runtime
ARG APP_UID=1000
ARG APP_GID=1000
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HF_HOME=/home/app/.cache/huggingface \
    EMBEDDING_DEVICE=cpu \
    RERANKER_DEVICE=cpu

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app backend/ ./backend/
COPY --chown=app:app config/ ./config/
COPY --chown=app:app scripts/ ./scripts/
RUN mkdir -p data/processed docs/evals logs /home/app/.cache/huggingface \
    && chown -R app:app /app /home/app/.cache

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5)"]

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
