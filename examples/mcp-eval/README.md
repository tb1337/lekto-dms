# Trying Lekto's MCP server with a real client

How well an AI assistant works with Lekto through MCP, measured: a dozen questions about the
example documents of one household (`examples/documents`), each with the answer the manifest
gives, asked through Claude Code with nothing but Lekto's tools. The run counts the right
answers and the tokens (umsetzungsplan "MCP", decision 13). It costs what the calls cost, so it
runs by hand, not in CI.

Standard library only, like `examples/model-calls`.

| File         | What it does                                                                                                   |
| ------------ | -------------------------------------------------------------------------------------------------------------- |
| `seed.py`    | Creates the contacts, types and fields of the manifest and uploads its 321 files with their metadata as truth |
| `tasks.py`   | Writes `tasks.json`: the questions and the answers each accepts, reckoned from the manifest                    |
| `tasks.json` | The questions (checked in; run `tasks.py` again after the documents change)                                    |
| `run.py`     | Asks each question through `claude -p` with Lekto's MCP server, writes `results.json`, prints hits and tokens   |

## A Lekto of its own

Never seed an instance with real documents. A container with SQLite does (from the repository
root; the image of a release, or one built from the branch to try):

```sh
docker build --target runtime -t lekto:local .
openssl rand -hex 32 > /tmp/lekto-eval-key
docker run -d --name lekto-eval -p 127.0.0.1:8010:8000 \
  -e LEKTO_SECRET_KEY_FILE=/run/secrets/key -v /tmp/lekto-eval-key:/run/secrets/key:ro \
  -e LEKTO_ADMIN_USERNAME=admin -e LEKTO_ADMIN_PASSWORD=eval-only-password \
  -e LEKTO_COOKIE_SECURE=false -e LEKTO_PUBLIC_URL=http://localhost:8010 \
  -v lekto-eval:/data lekto:local
```

Sign in at <http://localhost:8010/ui> as `admin` and create an API token with scope
`read_write` (Konto, API-Tokens). Without a language model the documents are filed with the
manifest's metadata (channel `migration`); the text is read by OCR as always.

## Run

```sh
cd examples/mcp-eval
python seed.py --url http://localhost:8010 --token lekto_...   # then wait until the inbox shows nothing in processing
python run.py --url http://localhost:8010 --token lekto_...    # --model sonnet, --only t01,t07
```

`run.py` prints one line per task (right or not, the turns, the tokens) and the total;
`results.json` keeps the answers. Remove the instance with
`docker rm -f lekto-eval && docker volume rm lekto-eval`.
