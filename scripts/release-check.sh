#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: bash scripts/release-check.sh VERSION" >&2
  echo "example: bash scripts/release-check.sh 0.1.0" >&2
  exit 2
}

[[ $# -eq 1 ]] || usage
VERSION="$1"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
  echo "error: VERSION must be MAJOR.MINOR.PATCH, got: $VERSION" >&2
  exit 2
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

for cmd in git uv; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "error: required command not found: $cmd" >&2
    exit 2
  }
done

[[ "$(git branch --show-current)" == "main" ]] || {
  echo "error: releases must be made from main" >&2
  exit 1
}

[[ -z "$(git status --porcelain)" ]] || {
  echo "error: working tree is not clean" >&2
  git status --short >&2
  exit 1
}

echo "==> Refreshing origin/main"
git fetch --quiet origin main
LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git rev-parse origin/main)"
[[ "$LOCAL_SHA" == "$REMOTE_SHA" ]] || {
  echo "error: local main does not exactly match origin/main" >&2
  echo "  local:  $LOCAL_SHA" >&2
  echo "  remote: $REMOTE_SHA" >&2
  exit 1
}

NOTES="docs/releases/robo-papyro-v${VERSION}.md"
[[ -f "$NOTES" ]] || {
  echo "error: missing release notes: $NOTES" >&2
  exit 1
}
grep -Fq "## robo-papyro ${VERSION}" CHANGELOG.md || {
  echo "error: CHANGELOG.md has no robo-papyro ${VERSION} entry" >&2
  exit 1
}

echo "==> Syncing the locked workspace"
UV_FROZEN=1 uv sync --all-extras

ACTUAL_VERSION="$(uv run python - <<'PY'
from pathlib import Path
import tomllib

path = Path("packages/robo-papyro/pyproject.toml")
with path.open("rb") as f:
    print(tomllib.load(f)["project"]["version"])
PY
)"
[[ "$ACTUAL_VERSION" == "$VERSION" ]] || {
  echo "error: requested release $VERSION does not match robo-papyro package version $ACTUAL_VERSION" >&2
  exit 1
}

echo "==> Checking licenses"
uv run python ci/license_gate.py

echo "==> Checking formatting and lint"
uv run ruff check packages ci
uv run ruff format --check packages ci

echo "==> Running the full test suite"
uv run pytest -rs

echo "==> Checking the installed umbrella CLI"
uv run rp --help >/dev/null
uv run rp doctor

cat <<EOF

Release checks passed.
  version: robo-papyro $VERSION
  commit:  $LOCAL_SHA
  notes:   $NOTES
EOF
