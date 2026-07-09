#!/usr/bin/env bash
# One-time/occasional operator step: checks out the target repo and
# (re)builds its CocoIndex index inside the long-running cocoindex-code
# container. Not run automatically by the poll loop (spec §5) — rerun this
# manually whenever the indexed repo has moved on meaningfully.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

REPO="${1:-KanakaSoftware/polaris-FDD}"
REPO_DIR_NAME="$(basename "$REPO")"
WORKSPACE_DIR="$PROJECT_ROOT/.cocoindex-workspace"
REPO_PATH="$WORKSPACE_DIR/$REPO_DIR_NAME"

if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$PROJECT_ROOT/.env"
  set +a
fi

if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "GITHUB_TOKEN not set (check .env). Needed to clone $REPO." >&2
  exit 1
fi

mkdir -p "$WORKSPACE_DIR"

if [ -d "$REPO_PATH/.git" ]; then
  echo "Updating existing checkout at $REPO_PATH"
  git -C "$REPO_PATH" pull --ff-only
else
  echo "Cloning $REPO into $REPO_PATH"
  git clone "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git" "$REPO_PATH"
fi

export COCOINDEX_HOST_WORKSPACE="$WORKSPACE_DIR"
docker compose -f "$SCRIPT_DIR/../docker/cocoindex-compose.yml" up -d

echo "Building/updating the CocoIndex index for $REPO_DIR_NAME (first run also downloads the local embedding model — can take a while)..."
docker exec -w "/workspace/$REPO_DIR_NAME" cocoindex-code ccc index

echo
echo "Done. Try it: docker exec -w /workspace/$REPO_DIR_NAME cocoindex-code ccc search \"<query>\""
echo "To enable it in the agent, set in .env:"
echo "  COCOINDEX_CONTAINER_NAME=cocoindex-code"
echo "  COCOINDEX_REPO_DIR=$REPO_DIR_NAME"
