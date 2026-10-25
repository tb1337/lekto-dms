# CLAUDE.md

Lekto DMS (technical name `lekto`) is a self-hosted, headless document management system, a
replacement for Paperless-ngx. Python backend, hexagonal (ports and adapters); the REST API is the
only way in.

## Layout

| Path | Content |
| --- | --- |
| `backend/` | Python package `lekto`: `core` (domain, ports, services), `adapters` (inbound, outbound), `composition` |
| `web/` | Web UI: SvelteKit single-page app below `/ui`, client generated from `web/openapi.json` (see `web/README.md`) |
| `migration/` | Paperless-ngx migration client: separate uv project `lekto_migration` (`plan`, `check`, `prepare`, `run`; see `migration/README.md`) |
| `deploy/` | Runtime image files (s6-overlay services, `image/rootfs`), `test-image.sh`, `README.md` (operation, backup) |
| `examples/` | `model-calls/`: an example consumer of model calls through a webhook (Python, standard library only, Ollama) and a Compose extension to try it |
| `docker/` | Compose examples with the published images (`ghcr.io/tb1337/lekto:latest`): SQLite, Postgres, extensions (workers, S3, Ollama, Caddy, Traefik, nginx), migration; settings in `.env` (`.env.example`) |
| `.devcontainer/` | Devcontainer: Compose services (Postgres, Garage, Meilisearch), the fixed credentials for tests and CI (in `compose.yml`), the development instance (`README.md`, `dev.local.env.example`, `dev-setup.sh`) |
| `.vscode/tasks.json` | VS Code tasks that run the development instance from the devcontainer (start, stop, migrate, UI, reindex, render-pages, read-codes, migration) |
| `Dockerfile` | Stages `base`, `deps`, `app`, `s6`, `web` (UI build), `dev` (devcontainer) and `runtime` (production image); `migration/Dockerfile` builds `lekto-migration` |
| `.idea/` | Design documents in German: `architektur.md` (binding), `umsetzungsplan.md` |

## Commands

Run in `backend/` (inside the devcontainer, where all services are available):

```sh
uv sync
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run lint-imports
uv run pytest                    # all tests; integration tests skip if a service is unreachable
uv run pytest -m unit            # no external services
uv run pytest -m integration     # needs Postgres, Garage, Meilisearch, OCR programs
uv run pytest -n auto            # in parallel (pytest-xdist), as CI does
uv run lekto                     # validate LEKTO_ configuration (= python -m lekto.composition)
uv run lekto migrate             # bring the configured database to the newest schema
uv run lekto check-schema        # exit 0 if the schema is at the newest revision
uv run lekto api                 # serve the REST API until SIGTERM
uv run lekto worker              # run the worker until SIGTERM
uv run lekto --env-file ../.devcontainer/dev.local.env reindex   # a command on the dev instance
```

Web UI, in `web/` (`web/README.md`):

```sh
pnpm install
pnpm lint && pnpm format:check && pnpm check && pnpm test && pnpm build
pnpm dev                         # Vite on :5173 below /ui, /api proxied to the API on :8000
```

After an API change: `uv run python -m lekto.composition.openapi ../web/openapi.json` in `backend/`,
then `pnpm gen:api` in `web/` (a backend test fails while `web/openapi.json` is out of date).

Image (in the repository root; s6-overlay, `LEKTO_ROLE`, `PUID`/`PGID`; see `deploy/README.md`):

```sh
docker build --target runtime -t lekto:local .
deploy/test-image.sh lekto:local     # starts it with SQLite: migration, health, user, roles, a PDF, stop
docker build -t lekto-migration:local migration
```

Publishing a release on GitHub runs `.github/workflows/release.yml`: it builds `lekto` and
`lekto-migration` (amd64, arm64) with the version from the tag and pushes them to ghcr.io; the tags
(version, `beta`/`stable`, `latest`) come from `.github/scripts/image_tags.py`
(`python3 -m unittest discover -s .github/scripts`). The repository carries the version `0.0.0.dev0`.

Migration client, in `migration/` (`migration/README.md`):

```sh
uv sync
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

Run all five checks before every commit; with changes in `web/` also the web UI's checks, with
changes in `migration/` its checks.

## Architecture rules

- `core` is plain Python: no framework imports (no FastAPI, SQLAlchemy, Pydantic settings, structlog,
  S3 or HTTP clients). It logs through the standard library `logging`.
- Ports are Python protocols defined in `core/ports`; adapters implement them.
- Only `composition` knows which adapter implements which port. Inbound and outbound adapters never
  import each other, and neither do the inbound adapters (REST, MCP, worker, evaluation) among
  themselves: what more than one of them needs lives directly in `adapters/inbound`. `lint-imports`
  enforces this; keep it green.
- Every port gets an in-memory adapter and a contract test suite that every real adapter passes.
  The pattern matcher and the template renderer are the stated exceptions: the `regex` and
  `liquid` adapters need no service and serve the memory container too.
- Configuration is environment variables with prefix `LEKTO_` only, no config file. Secrets also work
  as `LEKTO_<NAME>_FILE`; both set is an error. See `backend/src/lekto/composition/settings.py`.
- Async throughout (FastAPI, SQLAlchemy async, async HTTP clients).
- Tests: `tests/unit` (marker `unit`) needs no services, `tests/integration` (marker `integration`) does.
  Markers are applied by directory. Contract suites live in `tests/contracts`; adapters subclass them.
  The SQL adapter runs them on SQLite (unit) and Postgres (integration).
- Schema changes: change `adapters/outbound/sql/tables.py` and add an Alembic revision in
  `adapters/outbound/sql/migrations/versions`; a test fails if the two differ.
- State change, domain events and follow-up jobs go through one `UnitOfWork` and one commit.
- The web UI talks to the REST API only. Every text a user reads is in `web/messages/{en,de}.json`;
  a test fails on raw text in markup.

## Labels

Every pull request carries exactly one category label from `.github/labels.yml` (`new-feature`,
`bugfix`, `enhancement`, `refactor`, `performance`, `maintenance`, `ci`, `documentation`,
`dependencies`, `dev-deps`, `breaking-change`); the Release Drafter builds the release notes from
them. A pull request that changes only `.idea/` gets `skip-changelog`. The version bump follows
the labels (`breaking-change` or `major`: major; `new-feature` or `minor`: minor; else patch).
Tobi publishes and tags the release from the draft.

## Language

Code, comments, commit messages and documentation (README, docstrings) are English. The design
documents in `.idea/` are German.

## Working style

- Plan first: read the design documents, propose a plan, wait for approval.
- If something is unclear or a decision is missing, ask before implementing. Do not deviate from
  the decisions in `.idea/architektur.md` on your own.
- New dependencies need agreement first.
- Small, thematically separate commits. Keep answers short and precise.
