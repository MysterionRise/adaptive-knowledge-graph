# GPU-enabled Dockerfile for FastAPI backend (CUDA support)
FROM nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04

WORKDIR /app

# Install Python and system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-dev \
    python3-pip \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set Python 3.11 as default
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install dependencies with GPU support
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --without pyirt,pybkt

# Install PyTorch with CUDA support (if not already in poetry)
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Copy application code
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY data/ ./data/

# Create logs directory
RUN mkdir -p logs

# Set environment variables for GPU
ENV CUDA_VISIBLE_DEVICES=0
ENV EMBEDDING_DEVICE=cuda
ENV RERANKER_DEVICE=cuda

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
