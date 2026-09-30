# Testing Guide

This document describes the testing infrastructure and practices for the Adaptive Knowledge Graph project.

## Test Structure

```
backend/tests/
├── conftest.py              # Shared fixtures and configuration
├── test_settings.py         # Settings and configuration tests
├── test_logging.py          # Logging configuration tests
├── test_main.py             # FastAPI application tests
├── test_docker.py           # Docker configuration validation
├── test_makefile.py         # Makefile target validation
└── test_poetry.py           # Poetry and dependency tests
```

## Running Tests

### Quick Start

```bash
# Run all tests
make test

# Run tests with verbose output
poetry run pytest -v

# Run specific test file
poetry run pytest backend/tests/test_settings.py

# Run specific test
poetry run pytest backend/tests/test_settings.py::test_settings_defaults
```

### Test Categories

Tests are marked with pytest markers:

```bash
# Run only unit tests
poetry run pytest -m unit

# Run only integration tests
poetry run pytest -m integration

# Skip slow tests
poetry run pytest -m "not slow"

# Run all tests including slow ones
poetry run pytest
```

### Coverage Reports

```bash
# Run tests with coverage
make test

# Generate HTML coverage report
poetry run pytest --cov=backend/app --cov-report=html
open htmlcov/index.html

# Check coverage percentage
poetry run pytest --cov=backend/app --cov-report=term
```

## Test Types

### 1. Unit Tests

Test individual functions and classes in isolation.

**Example**: `test_settings.py`
```python
def test_settings_defaults():
    """Test that settings load with default values."""
    settings = Settings()
    assert settings.app_name == "Adaptive Knowledge Graph"
```

**Markers**: `@pytest.mark.unit`

### 2. Integration Tests

Test how components work together.

**Example**: `test_main.py`
```python
def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
```

**Markers**: `@pytest.mark.integration`

### 3. Configuration Tests

Validate configuration files and infrastructure.

**Examples**:
- `test_docker.py` - Docker configuration validation
- `test_makefile.py` - Makefile target validation
- `test_poetry.py` - Poetry dependencies validation

### 4. Slow Tests

Tests that take longer to run (> 1 second).

**Markers**: `@pytest.mark.slow`

## Writing Tests

### Test Naming Conventions

- File names: `test_*.py`
- Test functions: `test_*`
- Test classes: `Test*`

### Using Fixtures

Fixtures are defined in `conftest.py`:

```python
def test_with_client(client):
    """Test using the FastAPI test client fixture."""
    response = client.get("/")
    assert response.status_code == 200

def test_with_temp_dir(temp_data_dir):
    """Test using temporary data directory."""
    assert temp_data_dir.exists()
```

### Async Tests

Use `pytest-asyncio` for async functions:

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result is not None
```

### Mocking

Use `pytest-mock` for mocking:

```python
def test_with_mock(mocker):
    mock_api = mocker.patch("backend.app.api.external_api")
    mock_api.return_value = {"status": "ok"}
    # Test code
```

## CI/CD Integration

### GitHub Actions

Our CI pipeline runs automatically on:
- Push to `main` or `claude/**` branches
- Pull requests to `main`

**Jobs**:
1. **Lint** - Code formatting and style checks (ruff)
2. **Type Check** - Static type checking (mypy)
3. **Test** - Unit and integration tests (pytest)
4. **Docker Build** - Validate Dockerfiles build
5. **Docker Compose** - Validate services start
6. **Docs Check** - Markdown linting
7. **Security** - Dependency scanning (safety, bandit)

### Pipeline Configuration

See `.github/workflows/ci.yaml` for details.

**Key features**:
- Caching of dependencies (Poetry virtualenv)
- Matrix testing (Python 3.11, 3.12)
- Coverage upload to Codecov
- Parallel job execution

### Local Pre-commit Checks

Run the same checks locally before committing:

```bash
# Install pre-commit hooks
poetry run pre-commit install

# Run all checks manually
make pre-commit

# Run individual checks
make lint          # Ruff linting
make format        # Ruff formatting
make type-check    # Mypy type checking
make test          # Pytest
```

## Code Coverage Goals

**Target**: 80% coverage minimum

**Current coverage**:
```bash
# Check current coverage
make test
```

**Coverage exclusions**:
- `*/tests/*` - Test files themselves
- `*/__init__.py` - Empty init files
- Prototype/experimental code (mark with `# pragma: no cover`)

## Docker Testing

### Build Validation

```bash
# Test CPU Dockerfile builds
docker build -f infra/docker/api.cpu.Dockerfile -t test-cpu .

# Test GPU Dockerfile builds
docker build -f infra/docker/api.gpu.Dockerfile -t test-gpu .
```

### Service Integration

```bash
# Start services
docker compose -f infra/compose/compose.yaml up -d neo4j opensearch

# Check health
docker compose -f infra/compose/compose.yaml ps

# View logs
docker compose -f infra/compose/compose.yaml logs

# Clean up
docker compose -f infra/compose/compose.yaml down -v
```

## Debugging Tests

### Run with Debug Output

```bash
# Verbose output
poetry run pytest -v

# Show print statements
poetry run pytest -s

# Stop on first failure
poetry run pytest -x

# Drop into debugger on failure
poetry run pytest --pdb
```

### Check Test Discovery

```bash
# List all tests
poetry run pytest --collect-only

# List tests matching pattern
poetry run pytest --collect-only -k "settings"
```

## Performance Testing

### Benchmark Tests

Use `pytest-benchmark` for performance tests:

```python
def test_extraction_performance(benchmark):
    result = benchmark(extract_concepts, sample_text)
    assert result is not None
```

### Profiling

```bash
# Profile test execution
poetry run pytest --profile

# Generate profiling data
poetry run pytest --profile-svg
```

## Test Data

### Fixtures

Shared test data in `conftest.py`:
- `test_settings` - Test configuration
- `client` - FastAPI test client
- `temp_data_dir` - Temporary data directory
- `mock_neo4j_uri` - Mock database URI
- `mock_opensearch_config` - Mock vector DB config

### Sample Data

Store sample data in `backend/tests/fixtures/`:
```
backend/tests/fixtures/
├── sample_textbook.json
├── sample_concepts.json
└── sample_graph.json
```

## Continuous Improvement

### Adding New Tests

When adding new features:
1. Write tests first (TDD) or alongside feature
2. Ensure coverage doesn't decrease
3. Add integration tests for API endpoints
4. Mark slow tests appropriately
5. Update this guide if adding new test patterns

### Test Review Checklist

- [ ] Tests pass locally
- [ ] Coverage maintained or improved
- [ ] Tests are deterministic (no flakiness)
- [ ] Appropriate markers used (unit/integration/slow)
- [ ] Fixtures reused where possible
- [ ] Test names are descriptive
- [ ] Edge cases covered

## Troubleshooting

### Tests Fail in CI but Pass Locally

**Common causes**:
- Environment variables not set in CI
- Missing dependencies in CI
- Path differences (use `Path` objects)
- Timezone differences

**Solution**: Check `.github/workflows/ci.yaml` environment setup

### Slow Test Suite

**Solutions**:
- Mark slow tests with `@pytest.mark.slow`
- Run fast tests during development: `pytest -m "not slow"`
- Use mocking for external dependencies
- Parallelize with `pytest-xdist`: `pytest -n auto`

### Import Errors

**Solutions**:
- Ensure `backend/app` is in PYTHONPATH
- Install project in editable mode: `poetry install`
- Check for circular imports

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [pytest-asyncio documentation](https://pytest-asyncio.readthedocs.io/)
- [ruff documentation](https://docs.astral.sh/ruff/)
- [mypy documentation](https://mypy.readthedocs.io/)

---

## Quick Reference

```bash
# Development workflow
make format        # Format code
make lint          # Lint code
make type-check    # Type check
make test          # Run tests
make pre-commit    # All checks

# CI/CD
git push           # Triggers GitHub Actions

# Coverage
make test          # Shows coverage report
open htmlcov/index.html  # View HTML report

# Docker
make docker-build  # Build images
make docker-up     # Start services
make docker-down   # Stop services
```
