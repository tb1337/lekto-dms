# syntax=docker/dockerfile:1
# lekto-migration: the migration client (Paperless-ngx to Lekto) as an image of its own, built
# and published with each release (`.github/workflows/release.yml`). Build context: `migration/`.
#
#   docker build -t lekto-migration:local migration
#   docker run --rm -it -v "$PWD:/work" --env-file .env lekto-migration:local plan
#
# The plan, the state and the reports live in the working directory /work (a bind mount or a
# volume). The client runs as 1000:1000; `docker run --user` gives /work another owner.

FROM ghcr.io/astral-sh/uv:0.11.33 AS uv

# --- build: the locked dependencies, then the client, into one environment -----------------------
FROM python:3.13.13-slim-trixie AS build

COPY --from=uv /uv /usr/local/bin/
ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/lekto-migration/venv
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

# --- runtime ---------------------------------------------------------------------------------------
FROM python:3.13.13-slim-trixie

COPY --from=build /opt/lekto-migration/venv /opt/lekto-migration/venv

# The version of the release, from its tag; only as a label (the client names no version).
ARG LEKTO_VERSION=0.0.0.dev0

ENV PATH="/opt/lekto-migration/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

LABEL org.opencontainers.image.title="Lekto migration" \
      org.opencontainers.image.description="Takes over a Paperless-ngx archive into Lekto through the two REST APIs" \
      org.opencontainers.image.source="https://github.com/tb1337/lekto-dms" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.version="$LEKTO_VERSION"

WORKDIR /work
USER 1000:1000
ENTRYPOINT ["lekto-migration"]
CMD ["--help"]
