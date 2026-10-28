## How to Fix an Advisory in a Transitive Dependency

The weekly dependency audit (`.github/workflows/dependency-audit.yml`) opens one tracking issue when `osv-scanner` finds a fixable advisory on `main` (#251 is this week's). When the package is transitive, nobody declares it, so Dependabot's weekly version-update groups never bump it. The fix is a manual `poetry update <package>` or, in `frontend/`, `npm update <package>`, and then a `poetry install` or `npm install` to update the package.

File (README.md):
```yaml
# Adaptive Knowledge Graph

A local-first AI tutor for open textbooks: knowledge-graph-enhanced retrieval
with cited answers and adaptive quizzes, running entirely on your own machine.

[![CI](https://github.com/MysterionRise/adaptive-knowledge-graph/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/MysterionRise/adaptive-knowledge-graph/actions/workflows/ci.yaml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11 | 3.12 | 3.13](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C
