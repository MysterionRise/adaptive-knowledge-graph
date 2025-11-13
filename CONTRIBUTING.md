# Contributing to Adaptive Knowledge Graph

Thank you for considering contributing to this project! This is an educational PoC designed for reuse and extension.

## Code of Conduct

Be respectful, inclusive, and professional. We're here to build something useful for education.

## How to Contribute

### 1. Fork and Clone

```bash
# Fork the repository on GitHub
git clone https://github.com/YOUR_USERNAME/adaptive-knowledge-graph.git
cd adaptive-knowledge-graph
```

### 2. Set Up Development Environment

```bash
# Install dependencies
poetry install

# Install pre-commit hooks
poetry run pre-commit install

# Start services
make docker-up
```

### 3. Create a Branch

```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Or for bug fixes
git checkout -b fix/bug-description
```

### 4. Make Changes

Follow our coding standards:

```bash
# Format code
make format

# Check linting
make lint

# Type check
make type-check

# Run tests
make test
```

### 5. Commit Changes

Use conventional commit messages:

```
feat: Add new feature
fix: Fix bug in component
docs: Update documentation
test: Add tests
refactor: Refactor code
style: Format code
chore: Update dependencies
```

Example:
```bash
git add .
git commit -m "feat: Add concept clustering with HDBSCAN"
```

### 6. Run Pre-commit Checks

```bash
# Run all checks
make pre-commit

# This runs:
# - ruff format
# - ruff lint
# - mypy type check
# - pytest
```

### 7. Push and Create PR

```bash
git push origin feature/your-feature-name
```

Then create a Pull Request on GitHub using the PR template.

## Development Guidelines

### Code Style

We use **ruff** for linting and formatting:

```bash
# Auto-format
make format

# Check style
make lint
```

**Key conventions**:
- Line length: 100 characters
- Use type hints where possible
- Docstrings for public functions (Google style)
- Descriptive variable names

### Type Hints

Use type hints for function signatures:

```python
from typing import List, Dict, Optional

def extract_concepts(text: str, max_concepts: int = 10) -> List[Dict[str, float]]:
    """Extract key concepts from text.

    Args:
        text: Input text to analyze
        max_concepts: Maximum number of concepts to extract

    Returns:
        List of concept dictionaries with scores
    """
    pass
```

### Documentation

- Update README.md for major features
- Add docstrings to public APIs
- Update TESTING.md for new test patterns
- Update COMPLIANCE.md for privacy/licensing changes

### Testing

**Required for all PRs**:
- Unit tests for new functions
- Integration tests for API endpoints
- Maintain or improve coverage (target: 80%)

```bash
# Run tests
make test

# Run specific test
poetry run pytest backend/tests/test_yourfile.py
```

**Test markers**:
```python
@pytest.mark.unit
def test_unit():
    pass

@pytest.mark.integration
def test_integration():
    pass

@pytest.mark.slow
def test_slow_operation():
    pass
```

### OpenStax Attribution

**When working with textbook content**:
- Always include attribution in outputs
- Do not train models on OpenStax content
- Respect `PRIVACY_LOCAL_ONLY` setting
- Document any new content processing

## Project Structure

```
adaptive-knowledge-graph/
├── backend/app/
│   ├── api/              # REST + WebSocket routes
│   ├── core/             # Settings, logging
│   ├── kg/               # Knowledge graph logic
│   ├── nlp/              # NLP and LLM wrappers
│   ├── rag/              # Retrieval and RAG
│   └── student/          # Student modeling
├── frontend/             # Next.js UI
├── scripts/              # Data pipeline scripts
├── tests/                # Test suite
└── infra/                # Docker and deployment
```

## Common Tasks

### Adding a New API Endpoint

1. Define route in `backend/app/api/routes.py`
2. Add DTO in `backend/app/ui_payloads/`
3. Write tests in `backend/tests/test_api.py`
4. Update API docs (FastAPI auto-generates)

### Adding a New NLP Model

1. Add wrapper in `backend/app/nlp/`
2. Update settings in `backend/app/core/settings.py`
3. Add tests with mocks
4. Document VRAM requirements in README

### Adding a New Graph Edge Type

1. Update schema in `backend/app/kg/schema.py`
2. Add extraction logic in `backend/app/kg/edges.py`
3. Update Neo4j queries in `backend/app/kg/neo4j_adapter.py`
4. Add tests

## CI/CD Pipeline

Our GitHub Actions workflow runs on every push:

**Jobs**:
- ✅ Lint (ruff)
- ✅ Type Check (mypy)
- ✅ Test (pytest, Python 3.11 & 3.12)
- ✅ Docker Build (CPU & GPU)
- ✅ Docker Compose Validation
- ✅ Docs Check (markdown lint)
- ✅ Security Scan (safety, bandit)

**PRs must pass all checks to be merged.**

## Review Process

1. **Automated checks** - CI must pass
2. **Code review** - At least one approval required
3. **Documentation** - Check README/docs updated
4. **Testing** - Verify test coverage maintained
5. **Merge** - Squash merge to main

## Getting Help

- **Questions**: Open a [Discussion](https://github.com/yourusername/adaptive-knowledge-graph/discussions)
- **Bugs**: Open an [Issue](https://github.com/yourusername/adaptive-knowledge-graph/issues) with reproduction steps
- **Features**: Open an Issue with detailed proposal

## Areas We Need Help

### Phase 2: Data Ingestion
- OpenStax textbook fetcher optimization
- HTML parser improvements
- Additional textbook sources (philschatz mirrors)

### Phase 3: Knowledge Graph
- Better concept extraction algorithms
- Edge weighting improvements
- Graph visualization enhancements

### Phase 4: RAG & LLMs
- Prompt engineering for better QA
- Local LLM optimization (quantization)
- Retrieval quality improvements

### Phase 5: Adaptive Learning
- BKT/IRT implementation
- Recommendation algorithm improvements
- Assessment generation

### Phase 6: UI/UX
- Next.js frontend components
- Cytoscape.js graph interactions
- Accessibility improvements

### Phase 7: Evaluation
- RAGAS benchmark expansion
- A/B testing framework
- Performance metrics

## Recognition

Contributors will be:
- Listed in README acknowledgments
- Credited in release notes
- Given contributor badge

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

Your contributions involving OpenStax content must respect CC BY 4.0 attribution requirements.

---

## Quick Checklist Before Submitting PR

- [ ] Code formatted with `make format`
- [ ] Linting passes with `make lint`
- [ ] Type checking passes with `make type-check`
- [ ] Tests pass with `make test`
- [ ] Coverage maintained or improved
- [ ] Documentation updated
- [ ] Commit messages follow conventions
- [ ] PR template filled out
- [ ] OpenStax attribution maintained (if applicable)

---

**Thank you for contributing to educational technology! 🎓**
