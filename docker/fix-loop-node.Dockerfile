FROM python:3.12-slim

# Same base as fix-loop.Dockerfile, plus Node.js/npm for projects whose repo
# is JS/TypeScript (e.g. Angular) rather than Python — selected per-project
# via ProjectConfig.docker_image, not used by default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates curl gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /workspace

CMD ["sleep", "infinity"]
