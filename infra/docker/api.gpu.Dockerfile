# syntax=docker/dockerfile:1
# FastAPI backend, CUDA inference (NVIDIA GPU + NVIDIA Container Toolkit).
#   docker compose -f infra/compose/compose.yaml --profile gpu up -d --wait
#
# Ubuntu 24.04 ships Python 3.12 as its system Python. The locked torch wheel from PyPI (2.10.x
# on linux/amd64, pinned <2.11 in pyproject.toml) already bundles the CUDA 12.8 user-space
# libraries through the nvidia-*-cu12 wheels, so no extra PyTorch index is needed and the CUDA
# "base" image is enough: the "runtime" variant would duplicate ~2 GB of the same libraries. The
# host needs an NVIDIA driver that supports CUDA 12.8. Single stage, like api.cpu.Dockerfile.

ARG CUDA_IMAGE=nvidia/cuda:12.8.1-base-ubuntu24.04
FROM ${CUDA_IMAGE}

ARG POETRY_VERSION=2.4.1
ARG APP_UID=1000
ARG APP_GID=1000
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HF_HOME=/home/app/.cache/huggingface \
    CUDA_VISIBLE_DEVICES=0 \
    EMBEDDING_DEVICE=cuda \
    RERANKER_DEVICE=cuda

# Ubuntu 24.04 images come with an "ubuntu" user on uid/gid 1000; replace it with "app"
RUN if id -u ubuntu > /dev/null 2>&1; then userdel --remove ubuntu; fi \
    && groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY pyproject.toml poetry.lock README.md ./

# Locked runtime dependencies into /opt/venv (Poetry runs from its own throwaway venv), plus the
# spaCy model; the compilers and headers are purged again in the same layer.
RUN --mount=type=cache,target=/root/.cache \
    apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-dev build-essential \
    && python3 -m venv /opt/poetry \
    && /opt/poetry/bin/pip install "poetry==${POETRY_VERSION}" \
    && python3 -m venv /opt/venv \
    && /opt/poetry/bin/poetry install --only main --no-root --no-ansi \
    && python -m spacy download en_core_web_sm \
    && rm -rf /opt/poetry \
    && apt-get purge -y --auto-remove python3-dev build-essential \
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
