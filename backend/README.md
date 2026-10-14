# papiq backend

Python package `papiq`, structured as ports and adapters.

```
src/papiq/
  core/            domain core, framework-free
    domain/        entities and value objects (document, drawer, contact, ...)
    ports/         interfaces the core needs (Python protocols)
    services/      use cases: ingest pipeline, rules, permissions
  adapters/
    inbound/       call the core: REST API, MCP server, worker, evaluation
    outbound/      implement ports: database, object store, search, LLM, OCR, parser
  composition/     composition root: reads configuration, wires adapters to ports, the
                   commands of `python -m papiq.composition`
```

Dependency rules, enforced by `uv run lint-imports`:

- `core` imports nothing from `adapters` or `composition`.
- `core.domain` imports nothing from `core.ports` or `core.services`.
- Inbound and outbound adapters never import each other.
- Only `composition` knows which adapter implements which port.

Every port gets an in-memory adapter for core tests and a contract test suite that every real
adapter must pass.

## Core

- `core/domain`: users, drawers and shares, master data (contacts, document types, tags),
  field definitions and values, the document aggregate with the pipeline state machine and
  lanes, domain events, jobs and the permission rules. IDs are UUIDv7, timestamps are UTC.
- `core/ports`: repositories, processing log, outbox and job queue share one `UnitOfWork`, so
  a state change, its events and follow-up jobs are committed together (transactional outbox).
  `EventBus` delivers committed events at least once. The identity repositories (credentials,
  sessions, API tokens, external identities, failed sign-ins) are part of the unit of work too.
  Further ports: `ObjectStore`, `Clock`, `Ocr`, `DocumentParser`, `PreviewRenderer`,
  `PasswordHasher`, `SecretCipher`, `Totp`, `OidcProvider`, `LanguageModel`, `Embeddings`,
  `SearchIndex`, `PatternMatcher`, `WebhookSender`.
- `core/services`: use cases (users, drawers, master data, documents, pipeline, inbox,
  classification, rules, indexing, search, webhooks, maintenance). Each runs in one unit of work and checks the caller's rights.

`papiq.composition.container.build_memory_container()` wires all designed ports to their
in-memory adapters (fakes for OCR, parser and previews); `build_services()` creates the use
cases on top.

## Identity

`core/domain/identity.py` and `core/services/auth.py`; `User` itself only knows its role and
whether it is active. A deactivated user has no rights and cannot authenticate.

- Passwords: Argon2id (`adapters/outbound/crypto`, RFC 9106 low-memory profile: 3 passes,
  64 MiB, 4 lanes), at most four hashes at a time, in a worker thread. Normalised to Unicode
  NFKC; 12 to 256 characters, not the username, no rules on character classes. Hashes with
  older parameters are replaced at the next sign-in.
- Sign-in: unknown and deactivated users are checked against a dummy hash, so all failures take
  the same time and read the same. Failures are counted per account (also for unknown names;
  from the sixth on, the account backs off from 1 second, doubling up to 15 minutes; no hard
  lock) and per source address (30 within 15 minutes block it for 15 minutes; IPv6 addresses
  count per /64 network); the counts are
  in the database. Every attempt is counted atomically before it is checked (an upsert),
  blocking as if it fails, and taken back if it does not fail, so attempts that arrive
  together cannot pass the throttle at once. A blocked account refuses every attempt (`429`), also a correct password, so
  TOTP codes cannot be guessed. A blocked source refuses only wrong sign-ins (`429` instead of
  `401`, not counted for the source again); a correct sign-in from there succeeds, so failures
  from an address many users share (a proxy, NAT) lock nobody out. Success clears the
  account's count.
- TOTP (RFC 6238, pyotp), optional per user: set up with a new secret, which takes effect when a
  code confirms it; then ten recovery codes (80 bits each) are shown once and stored as SHA-256
  hashes. Codes of the previous and next 30-second step are accepted, each step only once. The
  secret is encrypted with AES-256-GCM (`PAPIQ_SECRET_KEY`), bound to the user id. Turning TOTP
  off needs a code or a recovery code, or an admin.
- Sessions: random 256-bit tokens, stored as SHA-256. They end after `PAPIQ_SESSION_IDLE_TIMEOUT`
  without use, after `PAPIQ_SESSION_MAX_AGE`, at sign-out, at deactivation and when the password
  changes or is reset (the caller's own session is renewed). Every sign-in starts a new session.
  Last use is written at most once a minute. The CSRF token of a session is derived from its
  token (HMAC), so nothing more is stored.
- API tokens: `papiq_` plus 256 random bits, stored as SHA-256; scope `read` or `read_write`,
  a name, optional expiry, last use. Shown once. They survive a password change unless the
  caller (or the admin resetting it) asks to revoke them, and are refused while the account is
  deactivated.
- Accounts: admins create users (optionally with a password), change roles, reset passwords,
  deactivate, turn TOTP off and remove links to identity providers. Deleting a user needs that
  they own no documents and their drawers are empty; it removes their drawers, the shares to
  them and their sign-in data. The last active admin cannot be demoted, deactivated or deleted.
- The first admin: `PAPIQ_ADMIN_USERNAME` and `PAPIQ_ADMIN_PASSWORD[_FILE]` create an admin at
  API start while there is no admin at all. Afterwards they are ignored; they never change an
  existing account. A name taken by another user stops the start.
- OpenID Connect (optional, one provider; `core/services/oidc.py`, `adapters/outbound/oidc`):
  Authorization Code Flow with PKCE (S256) through Authlib over httpx2. State, nonce, verifier
  and the target path are sealed (AES-GCM, `PAPIQ_SECRET_KEY`) into a value for a short-lived
  cookie, which binds the flow to the browser that began it; it expires after ten minutes. The
  ID token is checked with joserfc: signature with an asymmetric algorithm the provider
  announces, issuer, audience (`azp` with several), expiry and issue time (one minute of
  leeway), nonce. Endpoints and keys come from the discovery document, whose issuer must equal
  `PAPIQ_OIDC_ISSUER`; keys are fetched again once for an unknown key id. Accounts are linked by
  issuer and subject, never by e-mail; a signed-in user links their account through the same
  flow. Unknown accounts are refused unless `PAPIQ_OIDC_AUTO_CREATE` creates a user named by
  `PAPIQ_OIDC_USERNAME_CLAIM` (a taken name is refused). No local TOTP is asked for: the
  provider handles that. Unlinking needs a local password. The redirect after the callback goes
  only to a path on this site.
- The cleanup job also removes ended sessions and failure counts past their window.

## Persistence

`adapters/outbound/sql` implements the unit of work (all repositories, processing log, outbox,
job queue) and the event bus on SQLite or Postgres, selected by `PAPIQ_DB_TYPE`. It uses
SQLAlchemy 2 Core (async; aiosqlite, asyncpg); the domain classes are not ORM-mapped,
`tables.py` defines the tables and the repositories convert explicitly.

- Isolation is read committed with optimistic locking (`version` column) on both databases.
  On SQLite, reads run in autocommit mode and a unit takes the write lock with
  `BEGIN IMMEDIATE` before its first write; writers are serialized. A task must not open a
  second writing unit while its first one is still open: it would wait for its own lock until
  the busy timeout, so the adapter raises RuntimeError at once instead.
- Uniqueness is enforced by the database. Case-insensitive names are stored with a
  `name_key` column (Unicode case folding) under a unique index.
- Timestamps are UTC (`timestamptz`; on SQLite fixed-width UTC text), decimals exact (`numeric`;
  on SQLite text).
- Outbox events are written at commit. On Postgres, an advisory lock makes transactions with
  events commit one at a time, so `outbox.seq` follows commit order and a subscriber's position
  never skips a late commit. The event bus is polled (`dispatch`); handlers run outside of
  transactions; failed deliveries are kept per subscriber in `event_retries` and repeated with
  growing delay (`DeliveryRetry`) until they are given up. `purge` removes events every
  subscription has handled; `JobQueue.purge` removes finished jobs; `JobQueue.release` gives a
  job back unfinished without counting the attempt (`Job.tries`).
- Claiming jobs uses `FOR UPDATE SKIP LOCKED` on Postgres and the write lock on SQLite.

Migrations are one Alembic chain for both databases (batch mode on SQLite), in
`adapters/outbound/sql/migrations`. Apply them with `python -m papiq.composition migrate`; it
creates a missing SQLite file. `python -m papiq.composition check-schema [--wait SECONDS]` only
looks (exit 0 if the schema is at the newest revision of this version; a database migrated by a
newer version fails at once); the image's worker waits with it for the API container's migration.
A schema change needs both an edit of `tables.py` and a new
revision; a test compares the migrated schema with the table definitions.

## Object store

`PAPIQ_STORAGE_TYPE` selects `adapters/outbound/filesystem` or `adapters/outbound/s3`; both pass
the same contract suite. Keys are relative paths (`originals/<sha256>`, `documents/<id>/...`)
checked by `core.ports.object_store.check_key`. `put`/`get` hold an object in memory and suit
small objects; files of any size go through `upload`/`download`, which work on local files.

- Filesystem: one file per key below `PAPIQ_STORAGE_PATH`. Writes go to a hidden temporary file
  next to the target, are flushed to disk and renamed over it, so readers never see a partial
  object.
- S3 (aioboto3): files above 8 MiB are transferred in parts. Checksums are only sent where S3
  requires them, for compatibility with servers such as Garage. Path-style addressing is the
  default (`PAPIQ_S3_PATH_STYLE`).

`Container.aclose()` closes the database engine and the S3 client.

## Processing

A document goes through a graph of nodes (`core/domain/pipeline.py`, `GRAPH`; `GET /pipeline`
lists it), each node a job (`pipeline.node`): receive → OCR and pages side by side; OCR → parse →
the four signals side by side → judge → fields → apply rules → file; filing waits for the pages
too. Nodes that do not
need each other run as soon as their needs are met, so two workers may process one document at
once. `processing.nodes` of a document holds the state of every node of the current run
(`waiting`, `running`, `done` with its outcome, `skipped`) with start and end; the events
`document.node_started`, `document.node_deferred` (an attempt raised; the node waits for the
next one) and `document.node_completed` follow it. A node that fails stops the
document (red): nodes still running finish, nothing new starts. A retry repeats the failed
nodes, a reprocessing from node X repeats X and every node after it (from the judge also the
signals that ask no model, so new aliases, identifiers or a new model count); both start a new run, so
jobs of the old run are recognised as stale.

| Node | Input | Derivatives (object store) | Outcome |
| --- | --- | --- | --- |
| OCR (`OcrNode`) | `originals/<sha256>` | `documents/<id>/archive.pdf` (PDF/A with text layer) | uncertain if the archive is not PDF/A, with the reason; OK with a note if the original's digital signature is not in the archive |
| Pages (`PagesNode`) | `originals/<sha256>` | `documents/<id>/pages/<n>.webp` (every page, 1200 px wide; an image narrower than that keeps its size, each frame of a TIFF is a page), `documents/<id>/preview.webp` (first page, 400 px wide); sets `page_count` | failed if the file cannot be read |
| Parse (`ParseNode`) | the archive PDF | `documents/<id>/content.txt` (the text as it is set), `documents/<id>/content.json` (its lines and words with boxes) | failed if no text was recognised |
| Signals (`signal_llm`, `signal_classifier`, `signal_neighbours`, `signal_facts`) | `content.txt`, master data, the classifier's model, the search index | proposals in the log | OK, also when abstaining (`abstained` names why); only `signal_llm` fails, after two unfit answers |
| Judge (`JudgeNode`) | the signals' entries in the log, `content.txt` | contact, document type, tags, document date (applied if green) | see Understanding |
| Fields (`FieldsNode`) | `content.txt`, the fields of the type and the global ones | field values and the title (applied if checked) | see Understanding |
| Apply rules (`ApplyRulesNode`) | `content.txt` (only if a rule looks at the text), the rules | drawer, contact, type, title, tags, fields | uncertain on conflicts, refused actions and forced reviews; see Rules |
| File (`FileNode`) | the drawer | - | uncertain if the owner may no longer file into the drawer (field `drawer`) |

- A node that raises is retried (`PAPIQ_NODE_MAX_ATTEMPTS`, delay `PAPIQ_NODE_RETRY_DELAY`,
  doubling); it waits meanwhile (`document.node_deferred`); after the last attempt the
  document goes red. A damaged or encrypted file
  (`UnprocessableDocumentError`) fails at once. The processing log records input, output,
  engine version, reason and duration of every run.
- OCRmyPDF (`adapters/outbound/ocrmypdf`) runs as a child process per document with a time
  limit (`PAPIQ_OCR_TIMEOUT`); on timeout or cancellation the process group is killed. The job
  lease is the longest limit of a node (OCR, or twice `PAPIQ_LLM_TIMEOUT`) plus two minutes, so a node normally keeps its claim; if it overruns (e.g. a slow S3
  transfer), another worker takes the job over and the late result is discarded. A node
  interrupted by a stopping worker is released at once (`JobQueue.release`); that does not
  count against `PAPIQ_NODE_MAX_ATTEMPTS`.
- OCRmyPDF: `--skip-text` (pages with text are not recognised again), `--output-type pdfa`,
  languages `PAPIQ_OCR_LANGUAGES`. Images whose stated resolution gives an implausible page
  size (none, or 72 dpi from a phone) are scaled to the long edge of A4; transparency is put on
  white, CMYK is converted, all pages of a TIFF are kept. OCRmyPDF shares the CPU cores among
  `PAPIQ_WORKER_CONCURRENCY` jobs.
- Two kinds of file get a second OCRmyPDF run. A digitally signed PDF is processed with
  `--invalidate-digital-signatures`: the original keeps its signature (originals never change),
  the archive has none, and the OCR entry of the log says so (outcome OK, `note`). A file whose
  PDF/A conversion fails outright (OCRmyPDF exit code 1, for example an unusual colour space) is
  written as a plain PDF (`--output-type pdf`); the node is uncertain with the reason. When
  Ghostscript itself refuses a construct of the file (overprint mode, a font with CID 0; exit
  code 10), the archive is a plain PDF as well and the reason comes from Ghostscript's
  messages. Such a document is yellow until its owner confirms it; the file cannot be made
  PDF/A without changing its content.
- The text is read from the archive's text layer as it is set (`adapters/outbound/pdfium/
  layout.py`, in a thread, milliseconds per page): every line as printed, its words in columns
  on the page's grid, so a label keeps its amount and columns of figures line up; a printout
  in a fixed-pitch font keeps its exact columns; a page whose text runs across it (a table
  printed sideways, a scan OCR read sideways) is read that way, text up the margin along its
  direction. Words end at the gaps between the characters, not at spaces (some PDFs set none).
  Pages are separated by a form feed on a line of its own. Headers and footers stay in the
  text (the identifiers of a letter's footer among them). A document parsed before 0.2 keeps
  Docling's Markdown (`content.md`) until its text is read again (`reparse`); it is read
  meanwhile. The structure is Papiq's own JSON:
  the pages with their size, the lines and words with boxes in fractions of the page as shown.
  It replaced Docling in 0.2: on the documents compared (`.idea/umsetzungsplan.md`) Docling
  dropped headers and footers, merged the rows of forms and needed a minute and 2 GB per
  document.
- Previews: PDFium (pypdfium2) renders, Pillow encodes WebP. PDFium is not thread-safe; all
  its use in a process shares one lock.
- Quotes on the page: the judge and the fields node look up every quote of the model in
  the text layer of the archive (`TextLocator`, PDFium): case, spacing, line breaks, hyphens at
  line ends and the marks of Markdown do not matter. Each field check keeps up to five places
  (page and one box per line, fractions of the page as shown, its rotation applied) and whether
  the quote shows the value itself or only leads to it (`quote_shows_value`); `/review`
  returns both. Documents processed before this have none until they are processed again.
- What the model nodes (`signal_llm`, `fields`) send is kept beside the document, one file per
  node with every run
  (`documents/{id}/exchanges/<node>.json`: system and user message, the raw answer and the
  endpoint's whole usage report); owner and admins read it through
  `GET /documents/{id}/exchanges/{node}`. The files go with the document's other derivatives.
- Deleting a document queues `documents.remove_files` in the same transaction: the worker
  removes its derivatives and its original, unless a document of any owner still has the same
  file (failures are repeated up to five times, from one minute, doubling). The removal and an
  upload of the same file lock the original's key (`UnitOfWork.lock`: a Postgres advisory lock,
  on SQLite the write lock); under that lock the upload stores the original again if it is
  gone, so no document is left without its original.
- A document with an uncertain step stops before filing with status `review` (yellow) and waits
  in its owner's inbox; `document.filed` comes only when it is green. Confirming it (see the
  inbox below) lets processing continue up to filing.
- Known gap: an original is stored before its document is created; if creating fails (e.g.
  the drawer's rights changed meanwhile), the object stays without a document. Removing such
  objects is left to a later cleanup of the object store.

## Understanding

Four signals propose, the judge decides contact, document type, tags and document date, the
fields node reads the fields of the decided type and the title (`core/services/classification`,
the rules in `core/domain/verdict.py`).

- **`signal_llm`**: one request to an OpenAI-compatible chat completions endpoint
  (`adapters/outbound/openai_compat`, `PAPIQ_LLM_*`, prompt `propose-2`) for sender and recipient,
  type, tags, date, a title, the language, and the values of the fields of the type it chooses
  and of the global ones, each with the quoted passage. The answer must follow a JSON schema
  (`response_format` `json_schema`, or `json_object` for providers without schema support); an
  answer that does not fit is asked for once more, then the signal fails (red). Without a
  configured model it abstains, and the owner classifies.
- **`signal_classifier`**: TF-IDF of words and word pairs and a logistic regression per target
  (contact, type, each tag), trained on the confirmed documents (`PAPIQ_CLASSIFIER`, see
  Classifier). It abstains without a trained model.
- **`signal_neighbours`**: the `PAPIQ_NEIGHBOURS` most similar confirmed documents the owner may
  read, by the vector of the start of the text against the search index; their contact, type
  and tags come from the database. It abstains without embeddings or index.
- **`signal_facts`**: names and aliases of contacts standing whole in the text, identifiers of
  contacts (IBAN, VAT ID, customer number, mail domain), unknown IBANs and VAT IDs.

A signal *names* a value it is sure of: the model, a contact whose name or alias its sender
matches at least `PAPIQ_CONFIDENCE_THRESHOLD` (legal forms and punctuation aside) with no other
close, or a type or tag of the lists; the classifier, its best class from
`PAPIQ_CLASSIFIER_THRESHOLD` on; the neighbours, a value at least two and more than half of them
carry, a contact only if no other contact is carried by two of them as well (neighbours split
between senders are alike by their form, a pay slip's employee for one, and name no sender). A
signal naming another value contradicts: always yellow, with every candidate and its
sources. The judge's rule:

| Field | Green (no contradiction) | Otherwise |
| --- | --- | --- |
| Contact | hard evidence (its identifier, or its name or alias in the text) and a signal names it; or the model's sender matches it from `PAPIQ_CONTACT_SUGGEST_THRESHOLD` on and the classifier or the neighbours name it. Never the model's recipient | yellow with ranked candidates; an identifier alone is a suggestion; an unknown sender a new contact (an admin creates it) |
| Document type | two signals name it, or only the model and no other signal covers it (the classifier was not trained on it, no confirmed document carries it) | yellow; a type outside the list is proposed as new |
| Tags | set as a type is green | a suggestion; tags never make a document yellow |
| Document date | a valid date that appears in the text (`31.03.2026`, `31.3.26`, `2026-03-31`, `31. März 2026`, `March 31, 2026`, ...) | suggested |

Without the model's proposal the judge is uncertain; it fails (red) only if the model answered
and no signal recognised anything.

The fields node reads the fields of the decided type and the global ones. If the model asked
for the type the judge decided, its values are taken over; otherwise (after a type correction,
or for a document from before the signals) it asks the model for the missing ones (prompt
`extract-3`). Each field is required or optional per type it is assigned to, a global one by its
own switch:

| Field | Check | Not passed |
| --- | --- | --- |
| Required field | its value is found and passes | yellow |
| Optional field | no value is fine (left empty); a value given must pass | yellow |
| Amounts, numbers | read as written (`2.111,68 €`, `1,234.56`, `-12,50`; an ambiguous one as the text shows it, else in the document's language) and found in the text; the currency shown as code, sign or word, or, where the text shows none at all (a pay slip's bare numbers), `PAPIQ_DEFAULT_CURRENCY` | |
| Dates | as the document date; a date field must differ from the document date | the date is suggested |
| Text, link, choice, yes/no | the value, or the quoted passage, appears in the text (`ja`/`nein` read as yes or no) | |

The quoted passage must appear in the text as well. The title comes from the type's title
pattern (`{contact}`, `{document_type}`, `{document_date}`, `{document_date:YYYY-MM}` with
`YYYY YY MM DD`, `{filename}`, `{field:Name}`), else from the model, while the document still
has its file name or the title the machine gave it; a pattern missing a value falls back to the
model's title. Confirming in the inbox renders the pattern again with the decided values; a
rule replaces the machine's title without making the document yellow. Every check with its
candidates and the raw answer is in the processing log (`fields`, `answer`), so a proposal stays
traceable after a correction; the rules read them with `core.services.inbox.field_checks`.

The document text is sent between markers derived from its hash, and the model is told to treat
it as data. It can only answer with the fixed schema: there is no field for drawers, owners,
shares or actions, and additional fields make the answer unfit. Long documents are shortened to
`PAPIQ_LLM_INPUT_BUDGET` characters, a run of spaces counted once (the columns of the text as it
is set cost a model little; beginning and end kept, the middle left out); with many
tags, at most `PAPIQ_LLM_MAX_TAGS` are listed, those named in the text first; of the contacts,
the 20 the text names most (with their aliases).

**Privacy.** The shortened document text, the names of document types, tags and fields, and the
names of the contacts the text names go to the endpoint in `PAPIQ_LLM_BASE_URL`; the file, other
contacts and users do not. Every log entry of the two model nodes names the endpoint host and
the model. At start, a warning names every
configured model endpoint outside the local network (not loopback, private, link-local or a
local name), because document content leaves the system there.

**Ollama.** `PAPIQ_LLM_BASE_URL=http://<host>:11434/v1` (with `/v1`). Ollama does not take a
context size over this API and cuts longer prompts silently (often at 4,096 tokens); start it
with `OLLAMA_CONTEXT_LENGTH=8192` or more. Local models on a CPU are slow:
`PAPIQ_LLM_TIMEOUT` is per request, and the job lease allows twice that (one repeated request).

**Classifier.** One model for all users (`core/services/classifier.py`,
`adapters/outbound/sklearn`). Training examples are the documents whose metadata a person set or
confirmed (`confirmed_at`: confirming in the inbox, changing contact, type, tags, date or fields,
taking a document over); green documents do not train. A recurring job (`classifier.check`,
every ten minutes) queues the training (`classifier.train`) once `PAPIQ_CLASSIFIER_MIN_EXAMPLES`
documents are confirmed and no model exists, or `PAPIQ_CLASSIFIER_RETRAIN_AFTER` were confirmed
since the last one; `python -m papiq.composition train` and `POST /classifier/train` train at
once. Training also learns identifiers of contacts: one that stands in at least two confirmed
documents, all of one contact (the household's own IBAN stands on letters of many and is never
learned); a learned identifier an admin rejected stays rejected. The model is stored as `npz`
without pickle (`classifier/model-<n>.npz`, the latest three are kept) and predicted with numpy
alone, so a new scikit-learn version cannot break it. `GET /classifier` tells its state.

**After the update to 0.2.** Two things, in this order:

1. The search index gets the attribute `confirmed` the neighbours filter on. The migration
   raises the version of every confirmed document, so the worker's reconciliation at its start
   writes them again; vectors of unchanged text are kept, so this needs no embedding calls and
   no `reindex` (which would embed every document anew). Until it is through, the neighbours
   find fewer documents. Documents taken over before count as confirmed; the first training
   starts by itself once the worker runs.
2. 0.2 reads the text as it is set instead of Docling's Markdown. A document parsed before
   keeps its Markdown, which is read meanwhile, until `python -m papiq.composition reparse` (or
   `POST /pipeline/reparse`) has the worker read its text again; nodes, lane and metadata stay
   as they are. The search index then takes up the new texts, which embeds every document anew
   (with an embedding service elsewhere this takes a while: choose the time), and the
   classifier is trained on the new texts afterwards (`train`).

**Evaluation.** `python -m papiq.composition evaluate [--fake]` runs the synthetic documents in
`evaluation/` cold and trained and writes a report; see [evaluation/README.md](evaluation/README.md).

## Rules

Rules are data, not code (`core/domain/rules.py`, `core/domain/rule_engine.py`,
`core/services/rules`). A rule has a name, a priority (0 to 1000, default 100, higher first),
triggers, a tree of conditions and actions. Changing its content makes a new version; old
versions stay readable, so the processing log can refer to them. Enabling and disabling make no
version; deleting is a soft delete.

```json
{
  "name": "Telekom to household",
  "priority": 100,
  "triggers": ["ingest", "change"],
  "conditions": {"all": [
    {"field": "contact", "op": "is", "value": "<contact id>"},
    {"any": [{"field": "text", "op": "contains", "value": "Rechnung"},
             {"field": "text", "op": "matches", "value": "Kd\\.?-Nr"}], "not": true}
  ]},
  "actions": [
    {"type": "set_drawer", "drawer_id": "<drawer id>"},
    {"type": "add_tags", "tag_ids": ["<tag id>"]},
    {"type": "set_title", "template": "{contact} {document_date}"}
  ]
}
```

- **Scope.** A user rule (any user) acts on its owner's documents with all actions and files
  only into drawers its owner may write to. A global rule (admins) acts on every document, but
  only with `add_tags`, `remove_tags`, `set_field` and `force_review`: nothing that changes
  who sees a document. Everyone reads the global rules; user rules are read by their owner and
  admins (`all_users=true`).
- **Triggers.** `ingest`: the pipeline node `apply_rules`, when a document arrives. `change`:
  a person changed the metadata of a document whose processing is complete.
- **Conditions.** Groups `all` or `any`, each may be negated with `"not": true`; at most 5 deep
  and 50 conditions. Fields and operators:

  | Field | Operators |
  | --- | --- |
  | `contact`, `document_type` | `is`, `in`, `present`, `missing` |
  | `tags` | `contains` (has this tag), `in` (has one of), `present`, `missing` |
  | `channel` (Eingangskanal: `web`, `api`, `migration`) | `is`, `in` |
  | `text` | `contains` (normalised like the classification checks), `matches` (regular expression) |
  | `document_date` | `is`, `gt`, `lt`, `present`, `missing` |
  | `field` (with `field_id`) | by data type: text and link `is`, `in`, `contains`, `matches`; number, amount, date `is`, `gt`, `lt`; yes/no `is`; choice `is`, `in`; all `present`, `missing` |

  `matches` takes `case_sensitive` (default false). Patterns run with the `regex` package
  (`adapters/outbound/regex`) in a thread with a time limit (`PAPIQ_RULES_PATTERN_TIMEOUT`); a
  pattern that times out does not match and is logged. All patterns of one run on one
  document get two seconds together, a preview page twenty; the patterns left do not match. The text is the parsed text without
  markup, at most `PAPIQ_RULES_MAX_TEXT` characters; it is loaded only if a rule looks at it.
- **Actions.** `set_drawer`, `set_contact`, `set_document_type`, `set_title` (placeholders
  `{contact}`, `{document_type}`, `{document_date}`, `{filename}`), `add_tags`, `remove_tags`,
  `set_field`, `force_review` (with a reason).
- **Evaluation.** All conditions see the state before any rule acts; a rule's action never makes
  another rule match in the same run. Contact, type and tags the model set and no person
  confirmed are distrusted: a rule that matches only because of them does not file into a
  drawer that others see (shared or another user's); it is reported instead. Retroactively
  such a move is a conflict: it acts only where the person accepts it.
- **Combining.** A field set by one rule, or by several to the same value, is set. Different
  values are a conflict and nothing is set; priority never decides. A value a person decided
  in the current processing run is never replaced (the rule is logged as overruled): in the
  inbox, by a change, or the drawer chosen on upload or by moving the document; a value the model set and no person
  confirmed is not replaced either (conflict). Tags of all rules are combined; added by one and
  removed by another is a conflict.
- **On arrival** conflicts, refused actions and forced reviews make `apply_rules` uncertain: the
  document waits in the inbox. Confirming it there (`POST /documents/{id}/confirm`, optionally
  with `drawer_id`) decides the open fields and continues to filing; a forced review the owner
  saw counts as answered. Filing checks once more that the owner may file into the drawer; if
  not, confirming needs a `drawer_id` (`422` with `open_fields: ["drawer"]`).
- **On a change** (`PATCH /documents/{id}`) rules are edge-triggered: a rule acts only if it
  holds after the change and did not hold before. Fields the person set in this change, or
  decided before in this processing run, are not touched. Nothing turns yellow: what cannot be applied is only reported, in the `rules`
  block of the answer (to the owner). If the rules file the document where an editor who made
  the change can no longer read it, the editor's answer is only `{"id": …, "access": null}`.
  `POST /documents/{id}/dry-run` shows the same without storing anything.
- **Retroactively.** `POST /rules/{id}/apply/preview` lists the documents the current version
  would change, newest first, with changes and conflicts (a page looks at 200 documents at
  most). `POST /rules/{id}/apply` pins a version and applies it to the selected documents (at
  most `PAPIQ_RULES_APPLY_MAX_DOCUMENTS`) in the background, job `rules.apply`, 25 documents per
  job; conflicts only where accepted (`accept_conflicts`), forced reviews do not act. A user rule
  is applied by its owner to their documents, a global rule by anyone to the documents they may
  write to; rights are checked again per document. Progress: `GET /rule-applications/{id}`.
- **References.** Contacts, types, tags, fields and drawers a rule names must exist (`404`),
  drawers must be writable for the owner (`403`). Deleting one of them, or removing a choice a
  rule uses, disables the rules that use it with a reason; enabling checks again. Deleting a user
  removes their rules.
- **Log.** Every run is a processing log entry of node `apply_rules` with the rules and versions
  checked, matches, effects and notes. `model_version`: `rules` (the pipeline node),
  `rules:change` (after a change; it also records what the person changed), `rules:apply`
  (retroactive), `person` (a confirmation), `person:drawer` (a drawer chosen on upload or by
  moving). Later runs read from the log which values a person
  decided and which the model set.

## Search

Hybrid search in Meilisearch: full text and meaning (vectors) in one query. Without
`PAPIQ_MEILISEARCH_URL` there is no search; without `PAPIQ_EMBEDDING_BASE_URL` it works on words
only. `GET /api/v1/documents/search?q=…` takes the filters of `GET /documents`, `limit`,
`offset` (at most 1000 hits can be reached) and `semantic_ratio` (0 words only, 1 meaning only;
default `PAPIQ_SEARCH_SEMANTIC_RATIO`). Each hit carries the document as `GET /documents/{id}`
does, a score and a snippet whose matches are marked. `semantic` in the answer tells whether the
meaning took part.

- **The index follows the documents.** The indexing service subscribes to the document events
  (`search.index`) and queues one job per change; it writes the document and reads it back, up to
  three rounds, so a change made meanwhile is not lost. A failed job repeats after 30 s,
  doubling up to an hour, ten times; the last attempt writes the words without vectors. Renaming
  a contact, a type or a tag queues the documents that carry it: the index holds names for the
  search by words. A reconciliation compares the index with the database and queues what is
  missing, stale or gone: every `PAPIQ_SEARCH_RECONCILE_INTERVAL` and at every start of a worker.
  If the embedding endpoint is down, the document is written at once with the vectors it has
  and the job repeats for the new ones. If Meilisearch loses its data, the adapter sets the
  index up again; restart the worker or call `POST /search/reindex` to fill it without waiting
  for the next reconciliation.
- **Rebuild at any time.** `POST /search/reindex` (admins) or `python -m papiq.composition
  reindex` builds `<index>-rebuild` from the database and the object store while the active
  index keeps serving, swaps it in and reconciles what changed meanwhile. The index holds no
  information that is not in the database.
- **Rights.** The index query contains the rights (own documents in any lane; green documents of
  drawers the caller owns or that are shared with them). Every hit is checked against the
  database once more and the filter applied again, so a withdrawn share ends the search for that
  document at once, before the index has changed; a page can therefore hold fewer items than
  `limit`. Documents still in processing are in the index, for their owner only.
- **Sections.** The text (at most `PAPIQ_SEARCH_MAX_TEXT` characters) is cut into sections of
  about `PAPIQ_SEARCH_CHUNK_SIZE` characters, at most `PAPIQ_SEARCH_MAX_CHUNKS`; each gets a
  vector, and the first one starts with title, contact, type and tags. `PAPIQ_SEARCH_MAX_CHUNKS=1`
  gives one vector per document. A vector is made again only when model or section texts change.
- **Embeddings.** The query is embedded at request time (`PAPIQ_SEARCH_EMBED_TIMEOUT`); if the
  endpoint is down or slow, the search falls back to words (`semantic: false`).
  The model is `snowflake-arctic-embed2` with `PAPIQ_EMBEDDING_QUERY_PREFIX=query:` (compared with
  `bge-m3` and `qwen3-embedding:0.6b` in `evaluation/search/reports`).
  `PAPIQ_EMBEDDING_DIMENSIONS` is the length of the vectors and required with Meilisearch and an
  embedding endpoint; vectors of another length are refused (the query then goes by words).
  Changing the model means a rebuild. Some models want a prefix for queries
  and documents (`PAPIQ_EMBEDDING_QUERY_PREFIX`, `PAPIQ_EMBEDDING_DOCUMENT_PREFIX`).
- **Limits.** Meilisearch ranks the documents nearest in meaning even if no word matches, so
  a hybrid search always returns hits; there is no threshold yet. A rebuild occupies one worker
  loop for its time. On a CPU the embedding of the sections dominates the indexing cost;
  `evaluate-search` measures it for a model.
- **Health.** `GET /health` includes `search` when it is configured. If only the search is
  down, the status is `degraded` and the answer stays `200`: the API works without it.

**Evaluation of the embedding model.** `python -m papiq.composition evaluate-search [--fake]
[--models a,b] [--ratios 0,0.5,1]` indexes the documents of the evaluation set with each model in
a temporary Meilisearch index and runs the queries of `evaluation/search/queries.json`; see
[evaluation/README.md](evaluation/README.md).

## REST API

`python -m papiq.composition api` (with `PAPIQ_ROLE` `all` or `api`) serves
`adapters/inbound/rest` with Uvicorn on `PAPIQ_API_HOST`:`PAPIQ_API_PORT`. All routes are below
`/api/v1`; the OpenAPI document is `/api/v1/openapi.json`, the interactive docs `/api/v1/docs`.

Authentication: a session cookie from `POST /auth/login` or the OIDC callback, or a personal
API token as `Authorization: Bearer papiq_…` (a Bearer header wins over a cookie). Every route
depends on it except the five public ones (sign-in, OIDC start, info and callback, health); a
test calls every registered route without credentials and expects `401`. Requests that change
something need, with a session, the header `X-CSRF-Token` (from the sign-in answer or
`GET /auth/me`) and, with a token, the scope `read_write`; otherwise `403`. Changing sign-in
data needs a session, so a leaked API token cannot take over an account: the own password,
TOTP, tokens, sessions and links (`/auth/*`), and the admin endpoints that create users with a
password, reset passwords, turn TOTP off and remove links. Admins cannot reset their own
password or TOTP there; that goes through `/auth/*` with the current password or a code. Event streams check every 30
seconds that their session or token still holds and end otherwise.

The session cookie is `__Host-papiq_session`: HTTP-only, `Secure`, `SameSite=Lax`, `Path=/`, for
`PAPIQ_SESSION_MAX_AGE`; with `PAPIQ_COOKIE_SECURE=false` it is `papiq_session` without
`Secure`. Sign-in accepts JSON only, so a form on another site cannot sign anyone in.

| Endpoint | Purpose |
| --- | --- |
| `POST /auth/login` | Username, password, optional `code` or `recovery_code`; sets the cookie, returns the CSRF token |
| `POST /auth/logout`, `GET /auth/me` | Sign out; who is calling and how |
| `POST /auth/password` | Change the own password: other sessions end, `revoke_tokens` optional |
| `DELETE /auth/sessions` | End all other sessions |
| `POST /auth/totp`, `/totp/confirm`, `/totp/disable`, `/totp/recovery-codes` | TOTP |
| `GET/POST /auth/tokens`, `DELETE /auth/tokens/{id}` | Own API tokens |
| `GET /auth/oidc`, `/auth/oidc/login`, `/auth/oidc/callback`; `POST/DELETE /auth/oidc/link` | OpenID Connect |
| `GET /users`, `GET/PATCH/DELETE /users/{id}` | Accounts: list (others see active users' names), role and state, delete (admins) |
| `POST /users`, `POST /users/{id}/password`, `DELETE /users/{id}/totp`, `DELETE /users/{id}/oidc` | Create with password, reset password, turn TOTP off, remove links (admins, session only, not the own account) |
| `/contacts`, `/document-types`, `/tags`, `/fields` (`GET`, `POST`, `GET/PATCH/DELETE /{id}`) | Master data: read by all, changed by admins, deleted only when unused. Fields: name, choices and scope change, the data type does not; removing a used choice or narrowing the scope past documents with values is `409` |
| `GET/POST /drawers`, `GET/PATCH/DELETE /drawers/{id}`, `PUT/DELETE /drawers/{id}/shares/{user_id}` | Drawers and shares (owner) |
| `GET /documents/search` | Search: `q`, the filters of `GET /documents`, `limit`, `offset`, `semantic_ratio`; hits with snippet, `estimated_total`, `next_offset`, `semantic` |
| `POST /search/reindex` | Rebuild the search index in the background (admins); `202` |
| `GET /documents` | Readable documents, newest first; filters `contact_id`, `document_type_id`, `tag_id`, `drawer_id`, `lane`; `limit`, `cursor` |
| `POST /documents` | Upload (multipart: `file`, optional `drawer_id`, optional `channel=migration`; otherwise the channel is `web` with a session, `api` with a token); `202` with `id`, `status_url` |
| `GET/PATCH/DELETE /documents/{id}` | Metadata and state with the caller's access, `channel`; change (write access; the answer has the change rules' `rules` report for the owner); delete (owner or admin) |
| `POST /documents/{id}/dry-run` | A change as with `PATCH`, with the change rules, nothing stored: the result and the differences |
| `POST /documents/{id}/move` | Into another drawer (owner, or an admin without read access) |
| `GET /documents/{id}/original`, `/archive`, `/preview`, `/pages/{number}` | Files (read access); pages from 1 to `page_count` |
| `GET /documents/{id}/text` | The text as it is set (plain text, pages apart by form feeds) in pieces: `offset`, `limit`; `409` while not parsed |
| `GET /documents/{id}/log` | Processing log (owner or admin) |
| `POST /documents/{id}/retry` | Repeat the failed nodes (owner or admin) |
| `POST /documents/{id}/reprocess` | `{"from_node": "ocr"}`: process again from a node, with every node after it (owner or admin) |
| `GET /pipeline` | The graph: every node and what it needs, in graph order |
| `POST /pipeline/reparse` | Read the text of every document again in the background (admins, after the update to 0.2); `202` with `queued` |
| `GET /inbox` | The caller's yellow and red documents, newest first, with their open nodes and fields; `limit`, `cursor` |
| `GET /documents/{id}/review` | What the model proposed and how each field was checked (owner or admin) |
| `POST /documents/{id}/confirm` | Decide the open fields (`changes` as with `PATCH`, `accept_suggestions`, `drawer_id`), then continue from `resume_at` (`apply_rules`, or `fields` after a type change) up to filing (owner or admin); undecided fields: `422` with `open_fields` |
| `GET/POST /rules`, `GET/PUT/PATCH/DELETE /rules/{id}`, `GET /rules/{id}/versions`, `/versions/{number}` | Rules: list (`scope`, `include_disabled`, `all_users` for admins), create, change (new version), enable or disable, delete; see Rules |
| `POST /rules/{id}/apply/preview`, `POST /rules/{id}/apply`, `GET /rule-applications/{id}` | Apply a rule to existing documents: preview, start (`202`), progress |
| `GET /events` | Server-sent events of the documents the caller may read; `?document_id=` |
| `GET/POST /webhooks`, `GET/PATCH/DELETE /webhooks/{id}` | Webhooks: the caller's own (admins read everybody's, `?owner=`); create (the answer shows the secret once), change, switch on or off, delete; see Webhooks |
| `POST /webhooks/{id}/secret`, `POST /webhooks/{id}/test`, `GET /webhooks/{id}/deliveries` | Renew the secret (the old one signs 24 hours longer), send a test request, the delivery log (`before`, `limit`) |
| `GET /health` | Database, bucket or storage directory and, if configured, the search index reachable; `200` (`ok`, or `degraded` if only the search is down) or `503`, no authentication; not written to the access log |

- Uploads are streamed into a temporary file and hashed on the way; the limit
  `PAPIQ_UPLOAD_MAX_SIZE` applies while receiving (`413`). The type is recognised from the
  content (PDF, JPEG, PNG, TIFF; otherwise `415`). A file the owner already has: `409` with
  `existing_document_id`.
- Errors are problem details (RFC 9457, `application/problem+json`) and documented per endpoint.
- Documents and drawers the caller may not see are `404` with the same answer as missing ones;
  lists, filters and pages only ever contain readable documents (the repository query follows
  the permission rule, and the service checks every result again). Yellow, red and unfinished
  documents are the owner's only.
- Every answer below `/auth` carries `Cache-Control: no-store` (CSRF tokens, TOTP secrets,
  recovery codes, API tokens), also errors and redirects. The OpenAPI document, the docs and
  `/health` stay public.
- Request bodies other than uploads are bounded by `PAPIQ_REQUEST_MAX_SIZE`, by
  `Content-Length` before anything is read and by the bytes received otherwise (`413`);
  FastAPI would otherwise read a JSON body of any size into memory.
- Downloads go through a temporary file and carry `X-Content-Type-Options: nosniff`,
  `Content-Security-Policy: sandbox` and `Cache-Control: private, no-store`.
- `401` (with `WWW-Authenticate: Bearer`), `429` (with `Retry-After`) and `502` (identity
  provider) are problems like all errors. The access log shows the OIDC callback without its
  query (code and state).
- Event streams: the API subscribes to the event bus as `api.sse` and polls the outbox every
  `PAPIQ_EVENTS_POLL_INTERVAL`. Each event goes to the streams of the users who may read the
  document at that moment (other users once it is green). No replay: after reconnecting,
  clients fetch the state. `document.deleted` goes to the streams of the users who could read the
  document when it was deleted (the event carries their ids; the stream message does not). One API instance
  is assumed: several would share the `api.sse` subscription. While the API is down, its
  subscription holds back the purge of the outbox.
- On SIGTERM the event streams end at once, open requests get ten seconds, then the database
  engine and the S3 client are closed.

## Worker

`python -m papiq.composition worker` (with `PAPIQ_ROLE` `all` or `worker`) runs
`adapters/inbound/worker`:

- `PAPIQ_WORKER_CONCURRENCY` loops claim and run due jobs; each waits
  `PAPIQ_WORKER_POLL_INTERVAL` when nothing is due. One loop delivers outbox events
  (`EventBus.dispatch`) every `PAPIQ_EVENTS_POLL_INTERVAL`. Postgres `LISTEN/NOTIFY` is not
  used.
- Memory: OCRmyPDF takes about 150 MB per job, the worker itself about 0.5 GB; reading the
  text needs little. The OCR is bound by the CPU: OCRmyPDF shares the cores among
  `PAPIQ_WORKER_CONCURRENCY` jobs, so more loops than cores gain nothing.
- The cleanup (`maintenance.cleanup`, one job with a fixed dedup key; it goes before pipeline
  steps when due) runs every
  `PAPIQ_CLEANUP_INTERVAL` and removes finished jobs and delivered events older than
  `PAPIQ_RETENTION`, webhook delivery log rows of that age, ended sessions, stale counts of
  failed sign-ins and the previous secrets of webhooks whose grace period
  (`PAPIQ_WEBHOOK_SECRET_GRACE`) is over. The same loop runs the removal of a deleted
  document's files.
- Rule applications (`rules.apply`) run 25 documents per job, then queue the next job, so
  pipeline nodes do not wait behind them.
- `PAPIQ_WEBHOOK_CONCURRENCY` further loops deliver webhooks (see Webhooks); a receiver that
  does not answer holds up deliveries, never the pipeline.
- SIGTERM or SIGINT: no new jobs; running jobs may finish within
  `PAPIQ_WORKER_SHUTDOWN_TIMEOUT`, then they are cancelled and their jobs released to run again
  at once. Finally the database engine and the S3 client are closed.
- Failed event deliveries are repeated with doubling delay from one second up to an hour, at
  most `PAPIQ_EVENTS_MAX_ATTEMPTS` times. Several dispatchers under the same subscriber name
  may deliver an event twice (at least once is allowed).
- Every loop runs its units of work one after another, never nested, as SQLite requires.

## Webhooks

A user subscribes to document events and Papiq sends a signed `POST` to a URL (n8n, Home
Assistant, any service). Webhooks belong to the user who created them; the API is under
`/webhooks` (create, list, change, switch off, delete, renew the secret, test, delivery log).
Admins may do everything with every webhook: read it and its log, change, delete, test, renew the
secret (which then shows to them, once). Nobody sees a secret again after it was shown. What an
admin reads includes the target URL (which may be a capability URL) and, in the log, the document
IDs and event types of that user's deliveries.
At most `PAPIQ_WEBHOOKS_PER_USER` (20) per user.

**Events.** `document.received`, `document.node_started`, `document.node_deferred`, `document.node_completed`, `document.lane_changed`,
`document.filed`, `document.updated`, `document.deleted`, or `*` for all, also future ones. A
webhook only hears of documents its owner may read, as with the event stream: the right is
checked when the event is queued and again before every attempt, and a user who lost access in
between gets nothing (the log shows `dropped`). The body carries no lane, so a receiver
that wants the state of the document fetches it; `document.filed` is not sent while the document
is still being processed. `document.deleted` goes to those who could read the document
when it was deleted.

**The request.** `POST <url>`, `Content-Type: application/json`, `User-Agent: Papiq/<version>`,
and a body that names the event only; the receiver fetches details through the API with a token
of its own:

```json
{"id": "01999d5e-...", "type": "document.filed", "occurred_at": "2026-10-08T12:00:00Z",
 "document_id": "01999d5e-..."}
```

`id` is the event id: it is the same in every repeated attempt, so a receiver can recognise
events it has handled. Delivery is at least once and not in order; sort by `occurred_at`. The
test request (`POST /webhooks/{id}/test`) has `type: "webhook.test"` and `document_id: null`;
it goes out at once, to whatever address the webhook names, so a user may send at most ten per
minute (`429` with `Retry-After` beyond that; counted per API process).

**Signature** ([Standard Webhooks](https://www.standardwebhooks.com), so ready-made verification
libraries work). Three headers: `webhook-id` (the event id), `webhook-timestamp` (Unix seconds
of this attempt) and `webhook-signature`, `v1,<base64>` of the HMAC-SHA256 over
`<webhook-id>.<webhook-timestamp>.<raw body>` with the secret (`whsec_` and 32 bytes in Base64;
the key is the Base64-decoded part after the prefix). Right after the secret was renewed the
header holds two signatures separated by a space, one per secret; accept the request if one
matches. A receiver should:

1. read the raw body (not a re-serialised JSON),
2. recompute the signature and compare with `hmac.compare_digest`,
3. refuse a `webhook-timestamp` older than five minutes (protection against replay; every
   attempt has a fresh timestamp),
4. skip event ids it has handled already.

```python
import base64, hashlib, hmac, time


def verify(secret: str, headers: dict[str, str], body: bytes) -> bool:
    if abs(time.time() - int(headers["webhook-timestamp"])) > 300:
        return False
    key = base64.b64decode(secret.removeprefix("whsec_"))
    content = f"{headers['webhook-id']}.{headers['webhook-timestamp']}.".encode() + body
    expected = base64.b64encode(hmac.new(key, content, hashlib.sha256).digest()).decode()
    signatures = [part.split(",", 1)[1] for part in headers["webhook-signature"].split()]
    return any(hmac.compare_digest(expected, signature) for signature in signatures)
```

The same on the command line, for a body saved as `body.json` without changes:

```sh
KEY=$(printf %s "${SECRET#whsec_}" | base64 -d | od -An -vtx1 | tr -d ' \n')
{ printf '%s.%s.' "$WEBHOOK_ID" "$WEBHOOK_TIMESTAMP"; cat body.json; } \
  | openssl dgst -sha256 -mac HMAC -macopt hexkey:"$KEY" -binary | base64
# compare the output with the part after "v1," in webhook-signature
```

**Answers and repetition.** Any `2xx` answer is delivered. No answer (unreachable, timeout after
`PAPIQ_WEBHOOK_TIMEOUT`, certificate refused), `5xx`, `408`, `425` and `429` are repeated, up to
`PAPIQ_WEBHOOK_MAX_ATTEMPTS` attempts with `PAPIQ_WEBHOOK_RETRY_DELAY` doubling up to an hour
(30 s, 1, 2, 4, 8, 16, 32, 60, 60 minutes: about three hours). `3xx` and every other `4xx` are
final: redirects are never followed, since the signature would not hold for another target.
After `PAPIQ_WEBHOOK_DISABLE_AFTER` (20) deliveries given up in a row Papiq switches the webhook
off (`active: false`, `disabled_reason: failing`); switching it on again clears the count.
A receiver that is down delays the deliveries behind it, since the `PAPIQ_WEBHOOK_CONCURRENCY`
loops wait for it up to the timeout per attempt; the pipeline is not affected.

**The log** (`GET /webhooks/{id}/deliveries`, newest first) has one row per attempt: time,
event, `outcome` (`delivered`, `retrying`, `gave_up`, `dropped`), HTTP status, duration, error
and the time of the next attempt. The receiver's answer is neither stored nor shown. Rows are
removed after `PAPIQ_RETENTION`.

**Secrets.** Papiq generates the secret and shows it once, in the answer to creating a webhook
or renewing its secret. It is stored encrypted with `PAPIQ_SECRET_KEY` (the worker needs the key
too, to sign). Renewing keeps the old secret signing next to the new one for
`PAPIQ_WEBHOOK_SECRET_GRACE` (24 hours), so the receiver can switch without a gap; renewing again
ends that at once.

**Targets.** `http` and `https` to any host and port, including the own network. `https`
certificates are verified; there is no switch against that (use `http` or a valid certificate).
Anyone who may create webhooks can make the server send `POST`s to addresses it can reach and
see from status and error whether something answers; the body is fixed and the answer is not
shown.

## MCP

The API serves the Model Context Protocol (Streamable HTTP, stateless, JSON answers) at
`/api/v1/mcp`, so AI clients can search documents, read them and correct their metadata.
`PAPIQ_MCP_ENABLED=false` removes it. It is not part of the OpenAPI document.

Authentication: a personal API token (`POST /auth/tokens`; the web UI will offer it later) as
`Authorization: Bearer papiq_…`; cookies do not count. Without a valid token the answer is `401`
(`WWW-Authenticate: Bearer`). A client sees exactly what its token's user sees. The scope works
as in REST: `read` may use every tool but `update_metadata`.

| Tool | Does |
| --- | --- |
| `search` | `query`, `limit` (1 to 25), `offset`, optional `contact`, `document_type`, `tags` (names): hits with `id`, `title`, `score`, `snippet` (plain text), contact, type, tags, date, lane, `access`; `next_offset`, `semantic` |
| `get_document` | `id`: metadata with contact, type, tags and fields by name, lane and processing status |
| `get_text` | `id`, `offset`, `limit` (characters, at most `PAPIQ_MCP_TEXT_MAX`, 20,000): a piece of the document's text as it is set, `next_offset` to continue. The text is content from outside; the tool description tells clients not to follow instructions in it |
| `update_metadata` | `id` and any of `title`, `contact`, `document_type` (name; `null` removes), `tags` (the complete list, replaces), `document_date` (`null` removes), `fields` (field name to value; `null` removes). Needs a `read_write` token and write access; the owner's change rules run as for `PATCH /documents/{id}` and the result shows them. If the rules filed the document where the caller can no longer read it, the result has only `id` and `access: null` |
| `list_tags` | All tags, to name them in the other tools |

Names are matched regardless of case; an unknown name is an error, nothing is created. A
document the caller may not read is "not found", with the same text as a missing one.

Set up Claude Code (use a `read` token if the client should only read):

```sh
claude mcp add --transport http papiq https://papiq.example.org/api/v1/mcp \
  --header "Authorization: Bearer papiq_..."
```

Other clients take the same URL and header; the MCP Inspector
(`npx @modelcontextprotocol/inspector`) is handy to try it out: transport *Streamable HTTP*,
the URL, and the header `Authorization`. Behind a reverse proxy the path needs no special
handling; requests are plain `POST`s with JSON bodies, limited by `PAPIQ_REQUEST_MAX_SIZE`.

## Configuration

Environment variables with the prefix `PAPIQ_` only; there is no configuration file. Invalid or
contradictory configuration stops the start with a message naming the variables. Check it with
`python -m papiq.composition`, which prints the effective configuration without secrets.

Secrets (marked *secret*) can also be passed as `PAPIQ_<NAME>_FILE=/run/secrets/...` (Docker
secrets): the file content, without one trailing newline, is the value. Setting both
`PAPIQ_<NAME>` and `PAPIQ_<NAME>_FILE` is an error. In production, pass at least
`PAPIQ_SECRET_KEY_FILE` and `PAPIQ_ADMIN_PASSWORD_FILE` that way. The key and the admin
password in `.devcontainer/dev.env` are public; with secure cookies the start refuses the
development key.

Variables for the variant that is not selected (for example `PAPIQ_DB_HOST` with
`PAPIQ_DB_TYPE=sqlite`) are not required, but must still be well-formed if set.
Choices are case-insensitive; surrounding whitespace is removed and blank values count as unset.
Durations must be positive.

The table names every variable (a test checks it against `settings.py`). **Role** says which
service reads it: `API`, `Worker` or `both`; a container with `PAPIQ_ROLE=all` needs them all,
separate API and worker containers only theirs (the connection and storage settings in both).
Durations are seconds (`30`, `1.5`) or ISO 8601 (`PT1H`, `P7D`).

| Variable | Role | Default | Meaning |
| --- | --- | --- | --- |
| `PAPIQ_ROLE` | both | `all` | `all`, `api` or `worker`: which services run (the image's s6 scripts read it) |
| `PAPIQ_LOG_FORMAT` | both | `json` | `json` or `console` |
| `PAPIQ_LOG_LEVEL` | both | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `PAPIQ_DB_TYPE` | both | `sqlite` | `sqlite` or `postgres` |
| `PAPIQ_DB_SQLITE_PATH` | both | `data/papiq.db`; image: `/data/papiq.db` | SQLite only; local volume (WAL), never a network share |
| `PAPIQ_DB_HOST` | both | unset | required for `postgres` |
| `PAPIQ_DB_PORT` | both | `5432` |  |
| `PAPIQ_DB_NAME` | both | unset | required for `postgres` |
| `PAPIQ_DB_USER` | both | unset | required for `postgres` |
| `PAPIQ_DB_PASSWORD` | both | unset | *secret*; required for `postgres` |
| `PAPIQ_STORAGE_TYPE` | both | `filesystem` | `filesystem` or `s3` |
| `PAPIQ_STORAGE_PATH` | both | `data/objects`; image: `/data/objects` | filesystem only |
| `PAPIQ_S3_ENDPOINT_URL` | both | unset | required for `s3`, e.g. `http://garage:3900` |
| `PAPIQ_S3_REGION` | both | `us-east-1` |  |
| `PAPIQ_S3_BUCKET` | both | unset | required for `s3` |
| `PAPIQ_S3_ACCESS_KEY_ID` | both | unset | *secret*; required for `s3` |
| `PAPIQ_S3_SECRET_ACCESS_KEY` | both | unset | *secret*; required for `s3` |
| `PAPIQ_S3_PATH_STYLE` | both | `true` | Path-style addressing (Garage needs it) |
| `PAPIQ_API_HOST` | API | `0.0.0.0` | Where the API listens |
| `PAPIQ_API_PORT` | API | `8000` |  |
| `PAPIQ_UPLOAD_MAX_SIZE` | API | `100MiB` | Largest upload; bytes or with unit (`50MB`, `1GiB`); a proxy's body limit must allow it |
| `PAPIQ_REQUEST_MAX_SIZE` | API | `1MiB` | Largest body of every other request (JSON); larger ones get `413` |
| `PAPIQ_UI_DIR` | API | unset; image: `/opt/papiq/ui` | The built web UI (`web/build`), served below `/ui`; `/` leads there. Must contain `index.html`; unset serves the API only |
| `PAPIQ_FORWARDED_ALLOW_IPS` | API | unset; required with `PAPIQ_COOKIE_SECURE=true` | Reverse proxies whose `X-Forwarded-For` is trusted (comma-separated). Secure cookies mean a TLS-terminating proxy in front of Papiq: name its address, or the per-source throttle sees only the proxy. `*` only if the proxy sets the header itself, replacing what clients send |
| `PAPIQ_SECRET_KEY` | both | required | *secret*; 32 bytes base64 (`openssl rand -base64 32`); encrypts TOTP and webhook secrets, the worker decrypts the latter to sign. Keep it: without it they cannot be read. The development key is refused with secure cookies |
| `PAPIQ_ADMIN_USERNAME` | API | unset | The first admin, created at API start while there is no active admin; set together with the password |
| `PAPIQ_ADMIN_PASSWORD` | API | unset | *secret*; see above |
| `PAPIQ_SESSION_IDLE_TIMEOUT` | API | `P1D` | A session ends when unused this long |
| `PAPIQ_SESSION_MAX_AGE` | API | `P30D` | A session ends this long after sign-in; not shorter than the idle timeout |
| `PAPIQ_COOKIE_SECURE` | API | `true` | `false` only for development over plain HTTP |
| `PAPIQ_PUBLIC_URL` | API | unset | Where browsers reach Papiq (`https://papiq.example.org`); required with OIDC |
| `PAPIQ_OIDC_ISSUER` | API | unset | OpenID Connect: set issuer, client id and client secret together or none; the issuer is `https` and compared exactly. Register `<PAPIQ_PUBLIC_URL>/api/v1/auth/oidc/callback` as redirect URI |
| `PAPIQ_OIDC_CLIENT_ID` | API | unset | see above |
| `PAPIQ_OIDC_CLIENT_SECRET` | API | unset | *secret*; see above |
| `PAPIQ_OIDC_SCOPES` | API | `openid profile email` | Must contain `openid` |
| `PAPIQ_OIDC_DISPLAY_NAME` | API | `Single sign-on` | Name of the provider on the sign-in page |
| `PAPIQ_OIDC_AUTO_CREATE` | API | `false` | Create a user at the first sign-in of an unknown provider account |
| `PAPIQ_OIDC_USERNAME_CLAIM` | API | `preferred_username` | ID token claim that names such a user |
| `PAPIQ_WEBHOOKS_PER_USER` | API | `20` | Webhooks a user may have |
| `PAPIQ_WEBHOOK_SECRET_GRACE` | API | `P1D` | How long the old secret signs after renewing; the cleanup drops it afterwards |
| `PAPIQ_WEBHOOK_TIMEOUT` | Worker | `10` | Seconds per delivery attempt (1 to 120) |
| `PAPIQ_WEBHOOK_MAX_ATTEMPTS` | Worker | `10` | Attempts per delivery (1 to 50) |
| `PAPIQ_WEBHOOK_RETRY_DELAY` | Worker | `30` | Seconds before the second attempt, doubling after, at most an hour |
| `PAPIQ_WEBHOOK_DISABLE_AFTER` | Worker | `20` | Deliveries given up in a row until a webhook is switched off |
| `PAPIQ_WEBHOOK_CONCURRENCY` | Worker | `4` | Deliveries at the same time |
| `PAPIQ_MCP_ENABLED` | API | `true` | Serve MCP at `/api/v1/mcp` |
| `PAPIQ_MCP_TEXT_MAX` | API | `20000` | Characters one `get_text` call returns at most (1,000 to 1,000,000) |
| `PAPIQ_WORKER_CONCURRENCY` | Worker | `2` | Jobs at the same time, see Worker |
| `PAPIQ_WORKER_POLL_INTERVAL` | Worker | `1` | Seconds between looks for due jobs |
| `PAPIQ_WORKER_SHUTDOWN_TIMEOUT` | Worker | `30` | Seconds running jobs get to finish on SIGTERM |
| `PAPIQ_NODE_MAX_ATTEMPTS` | Worker | `3` | Attempts of a pipeline node that raises |
| `PAPIQ_NODE_RETRY_DELAY` | Worker | `30` | Seconds before the second attempt, doubling after |
| `PAPIQ_EVENTS_POLL_INTERVAL` | Worker | `1` | Seconds between outbox dispatches |
| `PAPIQ_EVENTS_MAX_ATTEMPTS` | Worker | `10` | Delivery attempts of an event per subscriber |
| `PAPIQ_CLEANUP_INTERVAL` | Worker | `3600` | Seconds between cleanups |
| `PAPIQ_RETENTION` | Worker | `P7D` | Age of finished jobs, delivered events and webhook log rows to remove |
| `PAPIQ_OCR_LANGUAGES` | Worker | `deu+eng` | Tesseract languages, joined by `+` |
| `PAPIQ_OCR_TIMEOUT` | Worker | `600` | Seconds per document for OCR |
| `PAPIQ_MEILISEARCH_URL` | both | unset | Without it there is no search (the API searches, the worker indexes) |
| `PAPIQ_MEILISEARCH_API_KEY` | both | unset | *secret*; the master key or a key with access to the index |
| `PAPIQ_MEILISEARCH_INDEX` | both | `papiq-documents` | The active index; a rebuild fills `<name>-rebuild` and swaps it in |
| `PAPIQ_MEILISEARCH_TIMEOUT` | both | `30` | Seconds per request |
| `PAPIQ_MEILISEARCH_TASK_TIMEOUT` | Worker | `120` | Seconds a write waits for its task |
| `PAPIQ_SEARCH_LOCALES` | both | `deu+eng` | Languages of the documents, ISO 639-3 codes joined by `+` (index settings) |
| `PAPIQ_SEARCH_SEMANTIC_RATIO` | API | `0.5` | Weight of the meaning against the words when a request does not say |
| `PAPIQ_SEARCH_EMBED_TIMEOUT` | API | `5` | Seconds to wait for the embedding of a query, then words only |
| `PAPIQ_SEARCH_MAX_TEXT` | Worker | `200000` | Characters of text per document in the index |
| `PAPIQ_SEARCH_CHUNK_SIZE` | Worker | `1500` | Characters per section with a vector |
| `PAPIQ_SEARCH_MAX_CHUNKS` | Worker | `8` | Sections with a vector per document |
| `PAPIQ_SEARCH_RECONCILE_INTERVAL` | Worker | `21600` | Seconds between comparisons of index and database |
| `PAPIQ_SEARCH_REBUILD_TIMEOUT` | Worker | `21600` | Seconds a rebuild may take |
| `PAPIQ_LLM_BASE_URL` | Worker | unset | OpenAI-compatible endpoint with version path (`http://ollama:11434/v1`); set together with the model or neither |
| `PAPIQ_LLM_MODEL` | Worker | unset | see above |
| `PAPIQ_LLM_API_KEY` | Worker | unset | *secret* |
| `PAPIQ_LLM_TEMPERATURE` | Worker | `0` | 0 to 2; 0 for repeatable answers |
| `PAPIQ_LLM_SEED` | Worker | unset | Passed to the endpoint, if set |
| `PAPIQ_LLM_TIMEOUT` | Worker | `300` | Seconds per request (`600` on a CPU) |
| `PAPIQ_LLM_RESPONSE_FORMAT` | Worker | `json_schema` | `json_object` for providers without JSON schema support |
| `PAPIQ_LLM_INPUT_BUDGET` | Worker | `12000` | Characters of document text per request (a run of spaces counts once) |
| `PAPIQ_LLM_MAX_TAGS` | Worker | `200` | Tags listed per request |
| `PAPIQ_EMBEDDING_BASE_URL` | both | unset | OpenAI-compatible endpoint; set together with the model or neither (the worker embeds sections, the API embeds queries) |
| `PAPIQ_EMBEDDING_MODEL` | both | unset | see above |
| `PAPIQ_EMBEDDING_API_KEY` | both | unset | *secret* |
| `PAPIQ_EMBEDDING_TIMEOUT` | both | `60` | Seconds per request |
| `PAPIQ_EMBEDDING_DIMENSIONS` | both | unset | Length of the vectors (`snowflake-arctic-embed2`, `bge-m3`: 1024); required with Meilisearch and an embedding endpoint |
| `PAPIQ_EMBEDDING_QUERY_PREFIX` | API | unset | Put before queries, for models that ask for it (`query:`) |
| `PAPIQ_EMBEDDING_DOCUMENT_PREFIX` | Worker | unset | Put before document sections, for models that ask for it |
| `PAPIQ_CONFIDENCE_THRESHOLD` | Worker | `0.9` | A field passes from this confidence on |
| `PAPIQ_CONTACT_SUGGEST_THRESHOLD` | Worker | `0.75` | An existing contact is suggested from this similarity on; not above the confidence threshold |
| `PAPIQ_DEFAULT_CURRENCY` | Worker | `EUR` | The currency of an amount in a document that shows no currency at all (ISO 4217) |
| `PAPIQ_CLASSIFIER` | both | `scikit-learn` | The classifier trained from confirmed documents; `none` turns it off |
| `PAPIQ_CLASSIFIER_MIN_EXAMPLES` | both | `20` | Confirmed documents before the first model is trained |
| `PAPIQ_CLASSIFIER_RETRAIN_AFTER` | both | `25` | Documents confirmed since the last model before it is trained again |
| `PAPIQ_CLASSIFIER_THRESHOLD` | Worker | `0.8` | A prediction this sure names its contact, type or tag |
| `PAPIQ_NEIGHBOURS` | Worker | `5` | Similar confirmed documents that vote on a new one (needs the search index with embeddings); `0` turns them off |
| `PAPIQ_RULES_PATTERN_TIMEOUT` | both | `0.2` | Seconds a regular expression of a rule may run per text or value (worker: rules; API: previews) |
| `PAPIQ_RULES_MAX_TEXT` | both | `200000` | Characters of text rules look at (1,000 to 10,000,000) |
| `PAPIQ_RULES_APPLY_MAX_DOCUMENTS` | both | `1000` | Documents per retroactive rule application (1 to 100,000) |

## Tests

- `tests/unit` (marker `unit`): no external services.
- `tests/integration` (marker `integration`): need Postgres, Garage or Meilisearch or the OCR
  programs (Tesseract, Ghostscript). Which services apply follows the
  `PAPIQ_` variables; a test skips itself if what it needs is not configured or not reachable.
  The devcontainer provides all of them.
- Sample files (scan, text PDF, photo, empty page, damaged PDF, Office file) are in
  `tests/samples`, generated by `make_samples.py`.

The markers are applied by directory, so new tests only need to be placed in the right folder.

`tests/contracts` holds the contract suites (classes such as `UnitOfWorkContract`). An adapter's
test module subclasses each suite as `Test...` and provides the adapter fixture
(`uow_factory`, `event_bus_factory`, `object_store`, `clock`, `ocr`, `parser`,
`preview_renderer`, `webhook_sender`); see
`tests/unit/adapters/memory/test_contracts.py`.

The SQL adapter runs the contract suites and `tests/sql_suite.py` (types, concurrency,
migrations) on SQLite in `tests/unit/adapters/sql` (a migrated database file per test) and on
Postgres in `tests/integration/adapters/sql` (a database of its own per test session, emptied
before every test). The CI job `integration` fails if any integration test skips.
