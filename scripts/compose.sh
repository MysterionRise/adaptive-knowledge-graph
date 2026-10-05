#!/usr/bin/env bash
#
# docker compose for this repository (used by the Makefile):
#   bash scripts/compose.sh <compose arguments>
#
# Adds --env-file .env when the repository-root .env exists (ports and passwords set there reach
# the containers) and infra/compose/compose.linux.yaml on a native Linux Docker Engine.

set -euo pipefail

# shellcheck source=lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
cd "$AKG_ROOT"
# Commit the containerised API reports in /api/v1/demo/provenance (evaluation reports)
GIT_SHA="${GIT_SHA:-$(git rev-parse HEAD 2> /dev/null || echo unknown)}"
export GIT_SHA
compose "$@"
