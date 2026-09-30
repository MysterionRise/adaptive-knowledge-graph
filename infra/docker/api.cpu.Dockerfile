# syntax=docker/dockerfile:1
# FastAPI backend, CPU inference.
#   docker compose -f infra/compose/compose.yaml --profile cpu up -d --wait
#   docker build -f infra/docker/api.cpu.Dockerfile -t adaptive-kg-api:cpu .
#
# One stage on purpose: the dependency layer is installed and cleaned up (compilers, Poetry,
# download caches) in a single RUN, so the image holds the virtualenv once. Copying it between
# stages would double the peak disk use of a build on linux/amd64, where the locked PyPI torch
# wheel also pulls the CUDA runtime wheels (nvidia-*-cu12; CPU-only wheels are tracked in #79).

ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ARG POETRY_VERSION=2.4.1
ARG APP_UID=1000
ARG APP_GID=1000
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HF_HOME=/home/app/.cache/huggingface \
    EMBEDDING_DEVICE=cpu \
    RERANKER_DEVICE=cpu

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY pyproject.toml poetry.lock README.md ./

# Locked runtime dependencies into /opt/venv (Poetry runs from its own throwaway venv), plus the
# spaCy model the concept extractor loads. Compilers are only needed for packages without a
# wheel on this platform and are purged again.
RUN --mount=type=cache,target=/root/.cache \
    apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && python -m venv /opt/poetry \
    && /opt/poetry/bin/pip install "poetry==${POETRY_VERSION}" \
    && python -m venv /opt/venv \
    && /opt/poetry/bin/poetry install --only main --no-root --no-ansi \
    && python -m spacy download en_core_web_sm \
    && rm -rf /opt/poetry \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*

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
