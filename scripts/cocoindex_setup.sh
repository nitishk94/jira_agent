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

# Read the branch to index from config/projects.yaml (single source of
# truth — same value the Fix-Loop's repo mirror uses) instead of hardcoding
# or defaulting to the repo's HEAD branch, which may not be where active
# development actually happens.
BRANCH="$(cd "$PROJECT_ROOT" && uv run python -c "
from jira_agent.config import get_settings
repo = '$REPO'
match = next((p for p in get_settings().projects if p.github_repo == repo), None)
print(match.default_branch if match else 'main')
")"
echo "Indexing branch: $BRANCH (from config/projects.yaml)"

mkdir -p "$WORKSPACE_DIR"

if [ -d "$REPO_PATH/.git" ]; then
  echo "Updating existing checkout at $REPO_PATH"
  git -C "$REPO_PATH" fetch origin "$BRANCH"
  # This checkout is a disposable scratch clone this script fully owns (not
  # the user's real working copy) — safe to drop untracked cruft `ccc init`
  # may have left (e.g. a fresh .gitignore) that would block switching
  # branches. Exclude .cocoindex_code itself so the index/settings survive.
  git -C "$REPO_PATH" clean -fd -e .cocoindex_code
  git -C "$REPO_PATH" checkout "$BRANCH"
  git -C "$REPO_PATH" pull --ff-only
else
  echo "Cloning $REPO ($BRANCH) into $REPO_PATH"
  git clone --branch "$BRANCH" "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git" "$REPO_PATH"
fi

export COCOINDEX_HOST_WORKSPACE="$WORKSPACE_DIR"
docker compose -f "$SCRIPT_DIR/../docker/cocoindex-compose.yml" up -d

# MSYS_NO_PATHCONV scoped to just these commands: /workspace/... is a path
# *inside* the Linux container, not a host path, so it must NOT be
# translated to a Windows path the way git/docker-compose host paths are.
if ! MSYS_NO_PATHCONV=1 docker exec -w "/workspace/$REPO_DIR_NAME" cocoindex-code test -f .cocoindex_code/settings.yml; then
  echo "Initializing CocoIndex project settings (local embedding defaults, no API key)..."
  MSYS_NO_PATHCONV=1 docker exec -i -w "/workspace/$REPO_DIR_NAME" cocoindex-code ccc init -f < /dev/null
fi

echo "Building/updating the CocoIndex index for $REPO_DIR_NAME (first run also downloads the local embedding model — can take a while)..."
MSYS_NO_PATHCONV=1 docker exec -w "/workspace/$REPO_DIR_NAME" cocoindex-code ccc index

echo
echo "Done. Try it (on Windows Git Bash, prefix with MSYS_NO_PATHCONV=1):"
echo "  docker exec -w /workspace/$REPO_DIR_NAME cocoindex-code ccc search \"<query>\""
echo "To enable it in the agent, set in .env:"
echo "  COCOINDEX_CONTAINER_NAME=cocoindex-code"
echo "  COCOINDEX_REPO_DIR=$REPO_DIR_NAME"
