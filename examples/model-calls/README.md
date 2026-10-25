# Model calls: an example consumer

An admin's webhook can take over Lekto's two requests to the language model: `propose` (the
signal `signal_llm`: sender, type, topic, tags, date, title, space and fields) and `extract`
(the fields the proposal did not give: the judge decided another type, or there is none). Lekto then sends the context
as a task and waits for the answer instead of calling `LEKTO_LLM_*`. The contract is in the
OpenAPI document (`/api/v1/openapi.json`) under `webhooks`: `external.propose` and
`external.extract`.

`consumer.py` answers both with a model on Ollama. Python 3.11 or later, standard library only:
a template to start from and a way to try model calls, not for production.

## How it works

1. Lekto posts the context (`contract` `propose-ext-1` or `extract-ext-1`) with the headers
   `lekto-task-id`, `lekto-callback`, `lekto-task-token` and `lekto-deadline`. The consumer
   takes it at once (202) and queues it.
2. It builds its own prompt from the context and asks Ollama (`/api/chat`) with the context's
   `answer_schema` as the format. The schema's descriptions carry the rules of Lekto's own
   prompt (evidence quoted literally, the recipient never the sender, amounts with currency).
3. It posts `{"status": "ok", "producer": "…", "answer": {…}}` to the callback with
   `Authorization: Bearer <token>`; if the model fails, `{"status": "error", "reason": "…"}`.

Lekto checks the answer as a model's: an answer that does not fit the schema is refused (422)
and the document is red, so is an error or no answer by the deadline. A good answer goes on to
the judge and the fields node, which check its values against the text.

The context also links `content.json` (words with boxes) and the page images
(`document.structure`, `document.page_images`), signed and valid until the deadline; this
consumer reads the text only.

## Try it with Docker Compose

Next to Lekto and Ollama from `docker/` (see `compose.yml` here):

```sh
cd docker
# .env: AGENT_TOKEN=<a long random value>, and LEKTO_PUBLIC_URL if not http://localhost:8000
docker compose -f compose.yml -f compose.ollama.yml -f ../examples/model-calls/compose.yml up -d
```

Then, signed in as admin, under **Webhooks**:

- New webhook: URL `http://agent:8080/`, header `Authorization` with the value
  `Bearer <AGENT_TOKEN>`, without signing, no events, **Model call: proposal**.
- A second one, the same with **Model call: fields**.

Upload a document; its node shows "Running externally" until the consumer answers
(`docker compose logs -f agent`). The document's processing log shows the context and the
answer where it otherwise shows the prompt.

## Try it in the devcontainer

With the development instance running (`LEKTO_PUBLIC_URL` set) and Ollama's API reachable:

```sh
OLLAMA_URL=<Ollama's address> AGENT_TOKEN=dev python3 examples/model-calls/consumer.py
```

and the webhooks as above with the URL `http://localhost:8080/`. Behind a proxy that wants a
key (such as Open WebUI's pass-through to Ollama; its documentation names the path), set
`OLLAMA_URL` to the address before `/api/chat` and the key in `OLLAMA_API_KEY`.

## Settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama's address, the part before `/api/chat` |
| `OLLAMA_API_KEY` | – | if set, sent to Ollama as `Authorization: Bearer` (a proxy in front of it) |
| `AGENT_MODEL` | `qwen3:8b` | the model |
| `AGENT_PORT` | `8080` | where the consumer listens |
| `AGENT_TOKEN` | – | if set, requests must carry `Authorization: Bearer <AGENT_TOKEN>` |
| `AGENT_SECRET` | – | if set (the webhook's `whsec_…`), requests must carry Lekto's signature |
| `LEKTO_URL` | – | if set, answers go there instead of `LEKTO_PUBLIC_URL` |
| `AGENT_MAX_CHARACTERS` | `24000` | the text is cut to this, its beginning and end kept |
| `AGENT_TIMEOUT` | `600` | seconds for one answer of Ollama |

Lekto's guard against instructions in the text and its text budget are the consumer's: Lekto
sends the text in full.
