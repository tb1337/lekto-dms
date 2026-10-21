# Lekto in the devcontainer: development and the development instance

The devcontainer (`devcontainer.json`, `compose.yml`) is where Lekto is developed and tested, and
where the **development instance** runs: a Lekto with real documents, started from VS Code tasks,
sharing Postgres, Garage and Meilisearch with the tests but with its own database, bucket and
search index. Nothing here is reachable from outside the machine; Lekto speaks plain HTTP on
`localhost`.

| Service (`compose.yml`) | Purpose |
| --- | --- |
| `dev` | The workspace: target `dev` of the `Dockerfile` (the system packages of the runtime image, Python 3.13 with uv, Node.js with pnpm, Git, GitHub CLI, Claude Code; zsh with Oh My Zsh from the feature `common-utils`) |
| `postgres` | Databases `lekto_dev` (the development instance) and `lekto_test_*` (integration tests, created and dropped per test); `lekto` is only the server's first database |
| `garage` | S3 object store; `garage-init` creates the key and the buckets `lekto-dev` (the development instance) and `lekto` (tests, below `tests/`) at every start |
| `meilisearch` | Search; indexes `lekto-dev-documents` (the development instance) and `lekto-test-*` (tests) |

The credentials of the services are fixed development values in `compose.yml`
(`x-test-environment`, also the environment of the `dev` container) and never leave the machine.
Ports 8000 (API), 5173 (Vite), 7700 (Meilisearch) and 3900 (Garage) are forwarded to the host.

## Two sets of data that never touch each other

| Use | Settings | Database | Bucket | Index |
| --- | --- | --- | --- | --- |
| Development instance (the tasks) | `dev.local.env` (not in the repository) | `lekto_dev` | `lekto-dev` | `lekto-dev-documents` |
| Tests (`uv run pytest -m integration`), CI | `x-test-environment` in `compose.yml`, the environment of the container; the tests derive their own names | `lekto_test_<random>` | `lekto`, prefix `tests/<random>/` | `lekto-test-<random>` |

The tests create and remove their databases, prefixes and indexes themselves. Running
`pytest -m integration` while the development instance is up changes nothing in `lekto_dev`,
`lekto-dev` or `lekto-dev-documents`. The volumes (`postgres-data`, `garage-meta`,
`garage-data`, `meilisearch-data`) outlive rebuilds of the devcontainer; `docker compose down -v`
in `.devcontainer/` deletes them all, including the development instance.
Until 21.10.2026 the Compose project was called `papiq-dev`; a devcontainer from then starts
with empty volumes. To take its data along, copy them once before the first start, with the old
containers stopped (on the host or from the devcontainer):

```sh
for v in postgres-data garage-meta garage-data meilisearch-data uv-cache; do
  docker volume create --label com.docker.compose.project=lekto-dev \
    --label com.docker.compose.volume=$v lekto-dev_$v
  docker run --rm -v papiq-dev_$v:/from:ro -v lekto-dev_$v:/to alpine:3.22 cp -a /from/. /to/
done
```

## Set the development instance up

Once, in the devcontainer (VS Code: Terminal → Run Task):

1. **Lekto: Set up dev instance** copies `dev.local.env.example` to `dev.local.env` with a fresh
   `LEKTO_SECRET_KEY` and creates the database `lekto_dev` (the bucket comes from
   `garage-init`, the index from Lekto). It never overwrites an existing `dev.local.env`. In a
   devcontainer that was started before the bucket `lekto-dev` existed, run `garage-init`
   once (`docker compose -f .devcontainer/compose.yml run --rm garage-init`, from the container
   or the host) or rebuild the container; `/api/v1/health` says `object_store: failed` until then.
2. Fill in `dev.local.env`: `LEKTO_ADMIN_USERNAME` and `LEKTO_ADMIN_PASSWORD` for the first admin
   (use the user name you have in Paperless, so the migration maps the documents to you), the
   address of your Open WebUI (`https://<host>/api`) in `LEKTO_LLM_BASE_URL` and
   `LEKTO_EMBEDDING_BASE_URL` and its API key in `LEKTO_LLM_API_KEY` and
   `LEKTO_EMBEDDING_API_KEY` (or remove the model variables to run without a language model: documents then stop yellow for the
   contact and the type, and the search works with words only). The other values fit the
   devcontainer. All variables: [backend/README.md](../backend/README.md#configuration).
3. **Lekto: Start** (below).

Keep `LEKTO_SECRET_KEY` (TOTP and webhook secrets are encrypted with it) and the admin password
in your password manager, not only in `dev.local.env`.

Never call the file `dev.env`: the commits before 21.10.2026, every tag up to v0.4 among them,
track a `.devcontainer/dev.env`, and checking one of them out overwrites an ignored file of that
name without asking.

## Start, stop, update

| Task | What it does |
| --- | --- |
| **Lekto: Start** | `Lekto: Migrate schema`, `Lekto: Build UI`, then `Lekto: API` and `Lekto: Worker` side by side, each in its own terminal |
| **Lekto: Stop** | Ends the API and worker tasks (SIGTERM; the worker finishes running jobs within `LEKTO_WORKER_SHUTDOWN_TIMEOUT`, 30 s) |
| Lekto: API, Lekto: Worker | One service alone (both run migration first; the API also builds the UI) |
| Lekto: Migrate schema | `lekto migrate` with `dev.local.env` |
| Lekto: Build UI | `pnpm build` in `web/`; the API serves `web/build` below `/ui` (`LEKTO_UI_DIR`) |
| Lekto: UI dev | Vite on <http://localhost:5173/ui/> with `/api` proxied to the API, for UI work with hot reload |
| Lekto: Rebuild search index | `reindex`: rebuild the search index from database and bucket (after a restore, a model change, or to add vectors) |
| Lekto: Render page images | `render-pages`: queue the page images of documents from before the pages node; the worker renders them |
| Lekto: Read codes | `read-codes`: queue reading the bar and QR codes of documents from before code reading; the worker reads them and keeps the identifiers each document shows |
| Lekto: Paperless migration | A new terminal in `migration/` with the variables of `dev.local.env` (`LEKTO_MIGRATION_*`), showing `lekto-migration --help`; the commands are typed there (see below) |

When the folder opens, only the task **zsh** starts: a terminal without `dev.local.env` (VS Code
asks once whether automatic tasks may run). After **Lekto: Start**, open
<http://localhost:8000/ui/> and sign in as the admin from `dev.local.env`; the API documentation
is at <http://localhost:8000/api/v1/docs>. The tasks use the terminals of VS Code; the logs are
there (`LEKTO_LOG_FORMAT=console`).

**Update after `git pull`:** `uv sync` in `backend/` and `pnpm install` in `web/` when the lock
files changed (the devcontainer runs both after a rebuild), then **Lekto: Stop** and
**Lekto: Start**: the start migrates the schema (a new Alembic revision is applied before API
and worker come up) and builds the UI anew. A schema migration cannot be undone: take a backup first
when the pull brings a new revision (`git log --stat -- backend/src/lekto/adapters/outbound/sql/migrations/versions`).

**Rebuild of the devcontainer** ("Rebuild Container"): the volumes stay, `dev.local.env` stays
(it is a file in the workspace), the tasks work as before.

## The language model

`dev.local.env.example` points at Open WebUI (in front of Ollama) with `qwen3:8b-ctx8k`
(classification) and Qwen3-Embedding 4B (search vectors), the models evaluated in
`.idea/architektur.md`. On a CPU a document takes 3 to 10 minutes in the model
(`LEKTO_LLM_TIMEOUT=600`); embeddings take about 4 s per section of 1500 characters on Ollama
with two vGPUs (21.10.2026), a query about 0.5 s. Single uploads are fine at any time. Mass runs (the migration with
embeddings on, `reindex` after switching embeddings on, a reprocessing of many documents) load
the model's machine for a long time: run them in sections of at most 40 minutes, not after
23:00 CET, and let Ollama unload the model afterwards (`keep_alive=0`). The migration below is
planned without embeddings and gets its vectors from one `reindex` run.

Document content is sent to these endpoints; the start of API and worker warns about every
endpoint outside the local network.

## Memory

A job needs little memory (OCRmyPDF about 150 MB, the worker about 0.5 GB); the OCR is bound
by the CPU. `dev.local.env.example` sets `LEKTO_WORKER_CONCURRENCY=3`; more jobs than the VM has
cores gain nothing (Docker Desktop or OrbStack: the cores of the VM, not of the Mac). See
[backend/README.md](../backend/README.md#worker).

## Migration from Paperless-ngx

[migration/README.md](../migration/README.md) describes the client. For the development
instance:

1. In Lekto (as the admin): Settings → API tokens → create a token with scope `read_write`;
   write it to the file `LEKTO_MIGRATION_LEKTO_TOKEN_FILE` names in `dev.local.env`
   (`/tmp/lekto-token`, outside the repository). Write the Paperless API key to
   `LEKTO_MIGRATION_PAPERLESS_TOKEN_FILE` (`/tmp/paperless-token`). `/tmp` is emptied when the
   container restarts; recreate the files then.
2. **Lekto: Paperless migration** opens a terminal for the client; run the phases there:
   - `uv run lekto-migration plan` reads Paperless and Lekto and writes
     `migration/migration-plan.yaml`: what is taken over, and how. Change it as you like; run
     it again after changes in Paperless (it asks before it writes).
   - `uv run lekto-migration check` writes nothing; the report in
     `migration/migration-reports/` lists what `prepare` and `run` would do, document by
     document.
   - `uv run lekto-migration prepare` creates the users, contacts, types, tags, fields and
     spaces the plan needs. Set up rules in Lekto now if they should act on the documents as
     they come.
   - `uv run lekto-migration run` takes the documents over (with OCR and Docling on the CPU and
     no language model it took about 12 s per document, 1500 documents in about 4.5 hours;
     reading the text as it is set takes milliseconds of that now) and aligns what was
     migrated before. Ctrl-C stops cleanly; running it again continues. The state is in
     `migration/migration-state.sqlite`.

Run the migration with the embedding variables commented out in `dev.local.env` (restart API and
worker after changing it): the pipeline then does not call Ollama for every document. Afterwards
switch them on again, restart, and run **Lekto: Rebuild search index** once to get the vectors.
The rebuild runs in one go and cannot be split: measured in M13 over the reverse proxy it took
about 10 s per document (1525 documents: over four hours), not the 0.7 s of the M6 measurement
on the NUC itself, so check the model's machine first or plan the time. Switching embeddings
**off** again while the index exists makes every indexing job fail (`vector_embedding_error`:
the index keeps its `userProvided` embedder); delete the index in Meilisearch then (`curl -X
DELETE -H "Authorization: Bearer $LEKTO_MEILISEARCH_API_KEY" $LEKTO_MEILISEARCH_URL/indexes/lekto-dev-documents`),
the worker recreates it at its next reconcile.

## Backup and restore

What to back up: the database `lekto_dev` and the bucket `lekto-dev`. Not Meilisearch (the
index is derived; `reindex` rebuilds it). Database first, then the objects (originals never
change; an object that arrived after the database copy is only an unused file). Keep
`LEKTO_SECRET_KEY` in your password manager.

The backup uses the Postgres container and an `rclone` image. Run the commands **on the host**,
in the repository folder (the paths of `-v` are host paths); from inside the devcontainer they
work as well, since it talks to the host's Docker, but `BACKUP` must then be the host's path of
the workspace (for example `/Users/you/lekto/backup/...`, not `/workspaces/lekto/...`). The
folder `backup/` in the repository is ignored by Git.

```sh
BACKUP=$PWD/backup/$(date +%Y-%m-%d)
mkdir -p "$BACKUP"
docker exec lekto-dev-postgres-1 pg_dump -U lekto -Fc lekto_dev > "$BACKUP/lekto_dev.dump"
docker run --rm --network lekto-dev_default -v "$BACKUP:/backup" \
  -e RCLONE_CONFIG_GARAGE_TYPE=s3 -e RCLONE_CONFIG_GARAGE_PROVIDER=Other \
  -e RCLONE_CONFIG_GARAGE_ENDPOINT=http://garage:3900 -e RCLONE_CONFIG_GARAGE_REGION=garage \
  -e RCLONE_CONFIG_GARAGE_ACCESS_KEY_ID=GKdeadbeefdeadbeefdeadbeef \
  -e RCLONE_CONFIG_GARAGE_SECRET_ACCESS_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  rclone/rclone:1.75.1 sync garage:lekto-dev /backup/objects
```

Restore (into the same devcontainer; stop Lekto first with **Lekto: Stop**):

```sh
docker exec lekto-dev-postgres-1 dropdb -U lekto --if-exists lekto_dev
docker exec lekto-dev-postgres-1 createdb -U lekto lekto_dev
docker exec -i lekto-dev-postgres-1 pg_restore -U lekto -d lekto_dev --no-owner < "$BACKUP/lekto_dev.dump"
docker run --rm --network lekto-dev_default -v "$BACKUP:/backup:ro" \
  -e RCLONE_CONFIG_GARAGE_TYPE=s3 -e RCLONE_CONFIG_GARAGE_PROVIDER=Other \
  -e RCLONE_CONFIG_GARAGE_ENDPOINT=http://garage:3900 -e RCLONE_CONFIG_GARAGE_REGION=garage \
  -e RCLONE_CONFIG_GARAGE_ACCESS_KEY_ID=GKdeadbeefdeadbeefdeadbeef \
  -e RCLONE_CONFIG_GARAGE_SECRET_ACCESS_KEY=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef \
  rclone/rclone:1.75.1 sync /backup/objects garage:lekto-dev
```

Then **Lekto: Start** and **Lekto: Rebuild search index**. `rclone sync` makes the target equal
to the source: a restore removes objects that are not in the backup. The Garage key above is the
fixed development key from `compose.yml`.

## Without VS Code

Every task is a shell command (`.vscode/tasks.json`). Lekto's commands are `lekto` (`lekto --help`
lists them); `--env-file` gives them the settings of the development instance instead of the
test settings the container's environment holds, for example

```sh
cd backend
uv run lekto --env-file ../.devcontainer/dev.local.env api      # and `worker` in a second terminal
uv run lekto --env-file ../.devcontainer/dev.local.env reindex
```

Without `--env-file`, `lekto` works on the tests' database, bucket and index.
