#!/usr/bin/env bash
# Prepare the development instance in the devcontainer, once; safe to run again:
#   - .devcontainer/dev.local.env from dev.local.env.example, with a fresh LEKTO_SECRET_KEY
#   - the database lekto_dev (the bucket lekto-dev is created by garage-init at every start,
#     the search index by Lekto itself)
# Run from the repository root (the VS Code task "Lekto: Set up dev instance" does).
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
env_file=$here/dev.local.env

if [ -e "$env_file" ]; then
  echo "dev.local.env exists; keeping it"
else
  key=$(openssl rand -base64 32)
  sed "s|^LEKTO_SECRET_KEY=$|LEKTO_SECRET_KEY=$key|" "$here/dev.local.env.example" >"$env_file"
  chmod 600 "$env_file"
  echo "dev.local.env written with a new LEKTO_SECRET_KEY; fill in LEKTO_ADMIN_USERNAME, LEKTO_ADMIN_PASSWORD the Open WebUI address and its API keys"
fi

set -a
# shellcheck disable=SC1090
. "$env_file"
set +a

cd "$here/../backend"
uv run python - <<'PY'
import asyncio
import os

import asyncpg


async def main() -> None:
    name = os.environ["LEKTO_DB_NAME"]
    connection = await asyncpg.connect(
        host=os.environ["LEKTO_DB_HOST"],
        port=int(os.environ.get("LEKTO_DB_PORT", "5432")),
        user=os.environ["LEKTO_DB_USER"],
        password=os.environ["LEKTO_DB_PASSWORD"],
        database="postgres",
    )
    try:
        exists = await connection.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name)
        if exists:
            print(f"database {name} exists")
        else:
            await connection.execute(f'CREATE DATABASE "{name}"')
            print(f"database {name} created")
    finally:
        await connection.close()


asyncio.run(main())
PY
echo "Done. Next: the task 'Lekto: Start'."
