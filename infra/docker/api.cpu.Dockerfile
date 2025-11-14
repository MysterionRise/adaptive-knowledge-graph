# CPU-only Dockerfile for FastAPI backend
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files and README (required by Poetry)
COPY pyproject.toml poetry.lock* README.md ./

# Install dependencies (CPU versions)
RUN poetry config virtualenvs.create false \
    && poetry install --only main --no-interaction --no-ansi --without pyirt,pybkt

# Copy application code
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY data/ ./data/

# Create logs directory
RUN mkdir -p logs

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
