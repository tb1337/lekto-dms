# lekto backend

Python package `lekto`, structured as ports and adapters.

```
src/lekto/
  core/            domain core, framework-free
    domain/        entities and value objects (document, space, contact, ...)
    ports/         interfaces the core needs (Python protocols)
    services/      use cases: ingest pipeline, rules, permissions
  adapters/
    inbound/       call the core: REST API, MCP server, worker, evaluation
    outbound/      implement ports: database, object store, search, LLM, OCR, parser
  composition/     composition root: reads configuration, wires adapters to ports, the
                   command line `lekto` (`python -m lekto.composition`)
```

Dependency rules, enforced by `uv run lint-imports`:

- `core` imports nothing from `adapters` or `composition`.
- `core.domain` imports nothing from `core.ports` or `core.services`.
- Inbound and outbound adapters never import each other.
- Only `composition` knows which adapter implements which port.

Every port gets an in-memory adapter for core tests and a contract test suite that every real
adapter must pass. Two adapters need no service and serve the memory container as well: the
pattern matcher (`regex`, a search with a time limit) and the template renderer (`liquid`).

## Core

- `core/domain`: users, spaces with their members, master data (contacts, document types, tags with
  their scopes and trees, `tag_tree.py`), field definitions and values, the document aggregate with the pipeline state machine and
  lanes, domain events, jobs and the permission rules. IDs are UUIDv7, timestamps are UTC.
- `core/ports`: repositories, processing log, outbox and job queue share one `UnitOfWork`, so
  a state change, its events and follow-up jobs are committed together (transactional outbox).
  `EventBus` delivers committed events at least once. The identity repositories (credentials,
  sessions, API tokens, external identities, failed sign-ins) are part of the unit of work too.
  Further ports: `ObjectStore`, `Clock`, `Ocr`, `DocumentParser`, `PageRenderer`,
  `PasswordHasher`, `SecretCipher`, `Totp`, `OidcProvider`, `LanguageModel`, `Embeddings`,
  `SearchIndex`, `PatternMatcher`, `WebhookSender`.
  Each is imported from its module (`lekto.core.ports.repository`, ...); the package
  re-exports nothing.
- `core/services`: use cases (users, spaces, master data, documents, pipeline, inbox,
  classification, rules, indexing, search, webhooks, maintenance). Each runs in one unit of work and checks the caller's rights.

`lekto.composition.container.build_memory_container()` wires all designed ports to their
in-memory adapters (fakes for OCR, parser and previews); `build_services()` creates the use
cases on top.

## Identity

`core/domain/identity.py` and `core/services/auth.py`; `User` itself only knows its role,
whether it is active and its display name. A deactivated user has no rights and cannot
authenticate.

- Profiles (`core/domain/profiles.py`, `core/services/profiles.py`): the display name is
  public (`UserOut.display_name`, shown instead of the username where set); the rest is private
  to the user and admins: aliases (a maiden name), birth date, e-mail and the person's own
  identifiers (`iban`, `tax_id`, `social_security_number`, `health_insurance_number`,
  `email_address`, each checked: the tax ID's and the social security number's check digits,
  the health insurance number's). A display name is unique across users regardless of case and
  never another user's username, nor a new username another user's display name (`409`; checked
  under a lock, so that a name shown stands for one person); choices of a user (members,
  hand-overs, whose number) show the username beside a display name that differs. Aliases are
  private and need not be unique: a `409` would tell whose alias it is. An identifier may
  belong to several users (a joint account), never to a user and a contact: one a contact
  entered by hand is `409`, a learned one gives way, and training never learns a person's
  identifier as a contact's, nor a customer or personnel number that is one of a person's
  values or stands in one (a pension fund's "Versicherungsnummer" is the start of the social
  security number), nor a person's e-mail domain. A contact's customer or personnel number may
  name the user it belongs to (`IdentifierOut.user_id`); such a number is private like the
  profile (issue #82): the user keeps their numbers at contacts in it (`ProfileOut.numbers`;
  `numbers` in the `PATCH` replaces those entered by hand, a learned one given is taken over,
  `declined_numbers` rejects learned ones that are not theirs), and only they and admins see
  them, here and at the contact. Who sees a contact's identifier (`identifiers.seen_by`, also in
  `GET /contacts`): admins all; anyone else the ones entered by hand that name nobody, their own
  numbers, and the learned ones of the spaces they are a member of; rejected ones only admins. A
  conflict names another contact only to whoever sees the identifier there, others get
  `identifier_taken`. An identity provider's `name` and
  `email` fill a new account's display name and e-mail, once, if free and valid. A profile
  needs a session: the own one at `/auth/me/profile`, anyone's for admins at
  `/users/{id}/profile`; an admin's API token (a migration) reads and sets only the display
  name and the e-mail address, a user's own token nothing. Nothing of a profile goes to the
  language model or the search index; the display name labels the user's personal space in the
  prompt.

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
  secret is encrypted with AES-256-GCM (`LEKTO_SECRET_KEY`), bound to the user id. Turning TOTP
  off needs a code or a recovery code, or an admin.
- Sessions: random 256-bit tokens, stored as SHA-256. They end after `LEKTO_SESSION_IDLE_TIMEOUT`
  without use, after `LEKTO_SESSION_MAX_AGE`, at sign-out, at deactivation and when the password
  changes or is reset (the caller's own session is renewed). Every sign-in starts a new session.
  Last use is written at most once a minute. The CSRF token of a session is derived from its
  token (HMAC), so nothing more is stored.
- API tokens: `lekto_` plus 256 random bits, stored as SHA-256; scope `read` or `read_write`,
  a name, optional expiry, last use. Shown once. They survive a password change unless the
  caller (or the admin resetting it) asks to revoke them, and are refused while the account is
  deactivated.
- Accounts: admins create users (optionally with a password), change roles, reset passwords,
  deactivate, turn TOTP off and remove links to identity providers. Deleting a user settles the
  spaces they leave behind in the same request (`GET /users/{id}/removal` names them; one left
  open: `409` with `blocking_spaces`): the documents of their personal space move into another
  space (`move_to`); a shared space they alone edit goes along if empty (`remove`), moves its
  documents and goes (`move_to`), or gets another editor and stays (`editor`). Documents move as
  an admin moves them by hand; all or nothing. It removes their personal space with its rules,
  their memberships and their sign-in data, and the documents they uploaded keep no uploader.
  The last active admin cannot be demoted, deactivated or deleted.
- The first admin: `LEKTO_ADMIN_USERNAME` and `LEKTO_ADMIN_PASSWORD[_FILE]` create an admin at
  API start while there is no admin at all. Afterwards they are ignored; they never change an
  existing account. A name taken by another user stops the start.
- OpenID Connect (optional, one provider; `core/services/oidc.py`, `adapters/outbound/oidc`):
  Authorization Code Flow with PKCE (S256) through Authlib over httpx2. State, nonce, verifier
  and the target path are sealed (AES-GCM, `LEKTO_SECRET_KEY`) into a value for a short-lived
  cookie, which binds the flow to the browser that began it; it expires after ten minutes. The
  ID token is checked with joserfc: signature with an asymmetric algorithm the provider
  announces, issuer, audience (`azp` with several), expiry and issue time (one minute of
  leeway), nonce. Endpoints and keys come from the discovery document, whose issuer must equal
  `LEKTO_OIDC_ISSUER`; keys are fetched again once for an unknown key id. Accounts are linked by
  issuer and subject, never by e-mail; a signed-in user links their account through the same
  flow. Unknown accounts are refused unless `LEKTO_OIDC_AUTO_CREATE` creates a user named by
  `LEKTO_OIDC_USERNAME_CLAIM` (a taken name is refused). No local TOTP is asked for: the
  provider handles that. Unlinking needs a local password. The redirect after the callback goes
  only to a path on this site.
- The cleanup job also removes ended sessions and failure counts past their window.

## Persistence

`adapters/outbound/sql` implements the unit of work (all repositories, processing log, outbox,
job queue) and the event bus on SQLite or Postgres, selected by `LEKTO_DB_TYPE`. It uses
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
`adapters/outbound/sql/migrations`. Apply them with `lekto migrate`; it
creates a missing SQLite file. `lekto check-schema [--wait SECONDS]` only
looks (exit 0 if the schema is at the newest revision of this version; a database migrated by a
newer version fails at once); the image's worker waits with it for the API container's migration.
A schema change needs both an edit of `tables.py` and a new
revision; a test compares the migrated schema with the table definitions.

## Object store

`LEKTO_STORAGE_TYPE` selects `adapters/outbound/filesystem` or `adapters/outbound/s3`; both pass
the same contract suite. Keys are relative paths (`originals/<sha256>`, `documents/<id>/...`)
checked by `core.ports.object_store.check_key`. `put`/`get` hold an object in memory and suit
small objects; files of any size go through `upload`/`download`, which work on local files.

- Filesystem: one file per key below `LEKTO_STORAGE_PATH`. Writes go to a hidden temporary file
  next to the target, are flushed to disk and renamed over it, so readers never see a partial
  object.
- S3 (aioboto3): files above 8 MiB are transferred in parts. Checksums are only sent where S3
  requires them, for compatibility with servers such as Garage. Path-style addressing is the
  default (`LEKTO_S3_PATH_STYLE`).

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
jobs of the old run are recognised as stale. A document keeps the lane its first run ended in
(`first_lane`: green went through without a review, yellow needed one, red failed); neither
a confirmation nor a later run changes it, so reports can tell how many documents went straight
through. For the page "System", Lekto keeps more as it happens (`core/domain/first_runs.py`,
port `ProcessingFacts`): the first run (when receiving began, when the run first stopped, how
long each node worked; `first_runs`), and per field the verdict at a person's first decision on
it (`field_verdicts`: `taken`, `accepted`, `corrected`, `added`, or `early` before the first run
stopped), with whether each signal named the person's value. Confirming in the inbox decides
every field, a confirming change the fields it sets and those the automation had set, a move the
space; a field keeps its first verdict. The statistics over both are counted live. `GET /automation`
shows them on the page "System" to every user (`AutomationService`): the documents by the lane of
their first run, what became of them, the history by month, the times (median and 90th
percentile, per step too) and the verdicts per field; `GET /automation/signals` the hits of each
signal per field. Both take the channels (`channel`, by default `web` and `api`), the period
(`period`: `30d`, `12m`, `all`; the history by month of all time reaches back five years at
most) and the time zone the months begin in (`tz`); a report is kept for a minute per API
process (`services/_kept.py`).

| Node | Input | Derivatives (object store) | Outcome |
| --- | --- | --- | --- |
| OCR (`OcrNode`) | `originals/<sha256>` | `documents/<id>/archive.pdf` (PDF/A with text layer); `documents/<id>/reading.json` (each word Tesseract read: text, confidence, box, line size; gone when Tesseract recognised no page); in the log, how well each recognised page was read (`readings`: words and unsure words below 60 % of Tesseract's confidence, and the same of the content words) | uncertain if the archive is not PDF/A, with the reason; OK with a note if the original's digital signature is not in the archive |
| Pages (`PagesNode`) | `originals/<sha256>` | `documents/<id>/pages/<n>.webp` (every page, 1200 px wide; an image narrower than that keeps its size, each frame of a TIFF is a page), `documents/<id>/preview.webp` (first page, 400 px wide); sets `page_count` | failed if the file cannot be read |
| Parse (`ParseNode`) | the archive PDF | `documents/<id>/content.txt` (the text as it is set), `documents/<id>/content.json` (its lines and words with boxes) | failed if no text was recognised |
| Signals (`signal_llm`, `signal_classifier`, `signal_neighbours`, `signal_facts`) | `content.txt`, master data, the classifier's model, the search index; `signal_facts` also the archive PDF | proposals in the log; `signal_facts` also `documents/<id>/codes.json` (the codes on the pages) | OK, also when abstaining (`abstained` names why); only `signal_llm` fails, after two unfit answers |
| Judge (`JudgeNode`) | the signals' entries in the log, `content.txt` | contact, document type, tags, document date (applied if green) | see Understanding |
| Fields (`FieldsNode`) | `content.txt`, the fields of the type and the global ones | field values and the title (applied if checked) | see Understanding |
| Apply rules (`ApplyRulesNode`) | `content.txt` (only if a rule looks at the text), the rules | space, contact, type, title, tags, fields | uncertain on conflicts, refused actions and forced reviews; see Rules |
| File (`FileNode`) | the space | - | - (rights hang on the space; filing always succeeds) |

- A node that raises is retried (`LEKTO_NODE_MAX_ATTEMPTS`, delay `LEKTO_NODE_RETRY_DELAY`,
  doubling); it waits meanwhile (`document.node_deferred`); after the last attempt the
  document goes red. A damaged or encrypted file
  (`UnprocessableDocumentError`) fails at once. The processing log records input, output,
  engine version, reason and duration of every run.
- OCRmyPDF (`adapters/outbound/ocrmypdf`) runs as a child process per document with a time
  limit (`LEKTO_OCR_TIMEOUT`); on timeout or cancellation the process group is killed. The job
  lease is the longest limit of a node (OCR, or twice `LEKTO_LLM_TIMEOUT`) plus two minutes, so a
  node normally keeps its claim; if it overruns (e.g. a slow S3 transfer), another worker takes
  the job over and the late result is discarded. The OCR of a document a person has read with
  the vision model extends its claim to `LEKTO_VLM_TIMEOUT` plus two minutes when it starts
  (`JobQueue.extend`): the job of a worker that died runs again after the short lease. A node interrupted by a stopping worker is
  released at once (`JobQueue.release`); that does not count against
  `LEKTO_NODE_MAX_ATTEMPTS`.
- OCRmyPDF: `--skip-text` (pages with text are not recognised again), `--deskew`,
  `--rotate-pages`, `--output-type pdfa`, languages `LEKTO_OCR_LANGUAGES`. A PDF with invisible
  text carries the layer of another OCR (a scanner's, an older archive's), which may be poor and
  says nothing of how well it read: it gets `--redo-ocr` instead (that layer is replaced,
  visible text kept, no deskewing, which OCRmyPDF does not allow then), and the log says
  `read_again`. A PDF whose text cannot be read gets `--force-ocr`: at least 30 % of a page's
  characters map to nothing (a font without a character map, as the ecoDMS PDF printer writes
  it, gives control characters), `--skip-text` would keep them and `--redo-ocr` keeps visible
  text. Every page is recognised from its image, the archive holds the pages as images (larger),
  and the log says why. Documents from before take the new reading when processed again from OCR. Images whose stated resolution gives an implausible page
  size (none, or 72 dpi from a phone) are scaled to the long edge of A4; transparency is put on
  white, CMYK is converted, all pages of a TIFF are kept. OCRmyPDF shares the CPU cores among
  `LEKTO_WORKER_CONCURRENCY` jobs.
- A vision language model (`LEKTO_VLM_*`, off without) reads a document only when a person
  asks for it (`POST /documents/{id}/vision`, editors and admins); nothing asks on its own. Without
  `LEKTO_VLM_BASE_URL` and `LEKTO_VLM_MODEL` the request answers `409` ("no vision language
  model is configured"), and a run that asked before the model was taken away fails at `ocr`
  ("a person asked for the vision language model, but none is configured"). The
  document is processed again from OCR, and OCRmyPDF runs with `--force-ocr --deskew` and the
  plugin `ocrmypdf/plugin.py` as OCR engine: Tesseract still tells orientation and skew, every
  page image goes to the model at no more than 1.15 megapixels (so that the service does not
  scale it again), and the model answers with each line and its box in pixels of that image
  (prompt `read-1`, JSON schema; once more after an answer that does not fit). The words of a
  line share its box by their length; OCRmyPDF writes the text layer from the lines. Boxes in
  thousandths of the image drifted on a dense statement and on a photo, pixel boxes fit every
  line (issue #53). The archive holds the pages as images under the model's text, and that text
  counts as OCR: the checks are the usual ones, words the model marks `[unreadable]` count as
  unsure (`LEKTO_POOR_READING_THRESHOLD`). The run keeps the request (`processing.vision`,
  revision 0021), so a retry asks the model again; reprocessing from `parse` and `reparse` keep
  the model's text (it is the archive's), reprocessing from `ocr` reads with Tesseract (the web UI asks first whether the model shall
  read again, and then calls `POST /documents/{id}/vision`). The archive's metadata names the
  reader: `/Creator` and `xmp:CreatorTool` say `Lekto, vision language model <model> (read-1)`. A page
  the model cannot read fails the node like the language model (`LanguageModelError`: retried,
  then red). The plugin gets its configuration in the environment of OCRmyPDF's process (the
  key apart, never logged) and leaves a record per page in a folder of ours. The log names
  model, endpoint and prompt (`output.vision`) and the tokens per call (`output.tokens`); the calls are kept like those of the
  language model (`exchanges/ocr.json`, the image as a placeholder). `GET
  /documents/{id}/reading` gives each recognised page and the advice to read with the model:
  `no_text` (red, the parse found no text) or `poor_page` (yellow or red, with a poorly read
  page); none once the model has read it.
- Three kinds of file get a further OCRmyPDF run. A digitally signed PDF is processed with
  `--invalidate-digital-signatures`: the original keeps its signature (originals never change),
  the archive has none, and the OCR entry of the log says so (outcome OK, `note`). A file with
  a colour space PDF/A cannot hold (exit code 1 `ColorConversionNeededError`, or exit code 10
  with a colour space as the issue) is run again with `--pdfa-backend ghostscript
  --color-conversion-strategy RGB`: the archive becomes PDF/A with its colours converted to
  RGB, and the log says so (outcome OK, `note`); only if that fails too is it a plain PDF. A file
  whose PDF/A conversion fails outright for another reason (OCRmyPDF exit code 1) is
  written as a plain PDF (`--output-type pdf`); the node is uncertain with the reason. When
  Ghostscript itself refuses a construct of the file (overprint mode, a font with CID 0; exit
  code 10), the archive is a plain PDF as well and the reason comes from Ghostscript's
  messages. Such a document is yellow until an editor of its space confirms it; the file cannot be made
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
  meanwhile. The structure is Lekto's own JSON:
  the pages with their size, the lines and words with boxes in fractions of the page as shown.
  It replaced Docling in 0.2: on the documents compared (`.idea/umsetzungsplan.md`) Docling
  dropped headers and footers, merged the rows of forms and needed a minute and 2 GB per
  document.
- Previews: PDFium (pypdfium2) renders, Pillow encodes WebP. PDFium is not thread-safe; all
  its use in a process shares one lock.
- Codes: `CodeReader` (`adapters/outbound/zxing`) renders each page of the archive in grey at
  300 dpi (an edge of at most 5000 px, at most 50 pages) and reads every format zxing-cpp knows
  (QR, Data Matrix, Aztec, PDF417, Code 128/39, EAN, ITF): format, text and box in fractions of
  the page; invalid and empty results are dropped, the same code on a page counts once. About
  0.1 to 0.3 s per page. A GiroCode (EPC069-12) is read as a credit transfer: payee, IBAN, BIC,
  amount, purpose (`core/domain/codes.py`).
- File metadata: `MetadataReader` (`adapters/outbound/pikepdf`) reads, on request, a PDF's
  version, PDF/A level, pages, document information and XMP packet (pikepdf), an image's
  format, size, resolution and EXIF without how its pixels are stored (Pillow); a damaged or
  encrypted file has none (`GET /documents/{id}/files`).
- Quotes on the page: the judge and the fields node look up every quote of the model in
  the text layer of the archive (`TextLocator`, PDFium): case, spacing, line breaks, hyphens at
  line ends and the marks of Markdown do not matter. Each field check keeps up to five places
  (page and one box per line, fractions of the page as shown, its rotation applied) and whether
  the quote shows the value itself or only leads to it (`quote_shows_value`); `/review`
  returns both. Documents processed before this have none until they are processed again.
- What the model nodes (`signal_llm`, `fields`, and `ocr` when the vision model read) send is
  kept beside the document, one file per node with every run
  (`documents/{id}/exchanges/<node>.json`: what each call sent – the system prompt, the
  document, the task and, after an unfit answer, the note to answer again; one `user` message for
  a page the VLM read, a webhook's context and calls before `propose-6` – the raw answer and the
  endpoint's whole usage report); editors and admins read it through
  `GET /documents/{id}/exchanges/{node}`. The files go with the document's other derivatives.
- Deleting a document queues `documents.remove_files` in the same transaction: the worker
  removes its derivatives and its original, unless a document in any space still has the same
  file (failures are repeated up to five times, from one minute, doubling). The removal and an
  upload of the same file lock the original's key (`UnitOfWork.lock`: a Postgres advisory lock,
  on SQLite the write lock); under that lock the upload stores the original again if it is
  gone, so no document is left without its original.
- A document with an uncertain step stops before filing with status `review` (yellow) and waits
  in the inbox of its space's editors; `document.filed` comes only when it is green. Confirming it (see
  Inbox) lets processing continue up to filing.
- Known gap: an original is stored before its document is created; if creating fails (e.g.
  the space's rights changed meanwhile), the object stays without a document. Removing such
  objects is left to a later cleanup of the object store.

## Inbox

The inbox is the way in (`core/domain/inbox.py`, `core/services/inbox.py`, `GET /inbox`): what
waits for a user stands there: the documents in the spaces they edit; an admin with
`all_users` has every user's, with their own seen. A document in a space someone only reads
never stands in their inbox. A green document moved into a space is new there for the editors
who could not read it before (handing it over into another user's personal space, too); the
members of the space it left keep their state, moving is no seeing.

- **Open**, newest first, in the one cursor format: in processing (`processing`, no lane yet),
  yellow (`review`) and red (`intervene`) until a person confirms them, and new documents
  (`new`) until the caller has seen them. Nothing leaves with time: a document leaves when a
  person confirms it or the caller sees it; a green document processed again leaves
  `processing` as it came, new only if its metadata changed. Each item keeps its open nodes and
  fields.
- **New** (`documents.new_at`): a processing run that ends green makes the document new, unless
  a person decided in it: confirmed it in the inbox, set its metadata while it ran, or it was
  taken over with the source system's metadata (`processing_decided`). A run that started on a
  document that was not green always does: its first run, a retry from red, a reprocessing of a
  yellow document, also with its metadata unchanged. A run that started on a green document
  does only if contact, type, topic, tags, date or fields differ from when it started
  (`processing_baseline`, a digest of them). Confirming out of yellow or red, by an editor or an
  admin, makes it new for no one.
- **Seen** is per user (`inbox_seen`, when each user saw a document last; new for them again
  once it became new after). The web UI reports it when the document view opens
  (`PUT /documents/{id}/seen`); reading through the API or MCP sets nothing. `DELETE` marks a
  document new again, `POST /inbox/seen` marks everything new in the inbox as seen. Seeing
  counts for a document that is new and unseen by the caller, in their inbox or an admin's of
  every user (one they saw since keeps when they saw it), and changes nothing else: not
  `confirmed_at`, the training, rules or the lane.
- **Done** (`tab=done`): what left the caller's inbox in the last 14 days, with how
  (`confirmed` out of yellow or red, for everyone, or `seen` by the caller), when and by whom;
  newest first by when it left, ties by id (the cursor names the last document, and when it
  left is looked up; `422` once that document is no longer done). The other tabs go by arrival.
  It comes from the seen marks and the latest confirmation of each document
  (`inbox_confirmations`, written with the confirmation); no history is kept. A move marks a
  document seen, silently (`inbox_seen.silent`), for whoever knew it already: it is not new for
  them, and it does not stand under done either, until they open it. The cleanup
  removes the confirmations after 14 days, and the seen marks that tell nothing any more (their
  document became new again since, or is new for no one).
- **Summary** (`GET /inbox/summary`): the count of each tab, everything open together (what the
  badge counts), and the worst lane among the open documents, red before yellow before green;
  null with nothing open but documents in processing.
- Lists and search mark what stands open in the caller's inbox (`in_inbox`), with one query
  for the seen marks of a page.
- Seen sends no event: it is the caller's own, so the web UI refreshes after its own action;
  another tab or device of the same user sees it with its next refresh. The other changes of
  what is open come with a document event (`document.lane_changed`, `document.deleted`).

## Tags

A tag has a scope (`TagScope`, fixed when it is made): `document` (a tag of documents, as before
0.3), `contact` (a contact group, "insurer"), `document_type` (a type group, "invoice" over
"medical bill") or `topic` (what a document is about with its contact, see Topics). Names are
unique per scope: a contact group may be named like a document tag.
Tags nest under a tag of the same scope (`parent_id`), at most five levels, without cycles
(`TagTree.check_parent`). Only the tag set is stored; its ancestors are derived (`TagTree`).

- **Documents** carry document tags only. A child and its parent set together leave the child
  (`TagTree.normalise`); a parent may be set alone. A document is found by a tag and by each of
  its ancestors.
- **Groups.** A contact and a document type are in any number of groups of their scope
  (`group_ids`); their documents inherit them with their ancestors. Groups are not stored at the
  document and not removed there.
- **Assignment.** A document tag is `auto` (the classification proposes and sets it) or `manual`
  (only a person or a rule sets it: statuses such as "to pay"); groups are always `manual`.
- **Shown.** Whether documents show a tag in their chips (default: on for document tags, off for
  groups); filters, search, rules and templates see it either way.
- **Filters** on a tag match the documents with it or a tag below it; on a group, those whose
  contact (type) is in it or a group below it. The core widens each tag or group by its
  descendants and hands the repository and the index sets ("one of these", all sets together,
  `DocumentFilter`), so no adapter walks a tree.
- **Counts** (`GET /tags?document_counts=true`): a document tag counts each document once that
  carries it or a tag below it; a group the documents whose contact (type) is in it or a group
  below it. A contact group and a topic also count their contacts (`contact_count`: in it or a
  group below it, enabling it or a topic below it), a type group its document types
  (`document_type_count`), each once.
- **Deleting** a tag works only without tags below it and while nothing uses it: no document,
  contact or type, and no rule (`409`, naming the rules; admins see all of them).
- **Renaming** a tag, nesting it elsewhere and changing the groups of a contact or type refresh
  the search index of the documents concerned (`search.refresh`).
- **Moving** a document tag or a group under another parent queues `tags.normalise`: what
  carries the tag (or one below it) and one now above it keeps only the one below, as if set
  anew (`master_data.normalise_tagged`). Documents are changed 200 per step, each an update
  of its own (`document.updated`, which refreshes its search entry), without touching lane or
  confirmation; a step holds the lock of the tag tree, reads the tree as it is then and queues
  the next step in the same commit (so a lease covers one step, and a tag moved back meanwhile
  is left alone). For a group the contacts or types (the index holds their groups with
  ancestors, which stay the same). A topic needs none: a document carries one, and a contact
  may enable a topic and one below it.

## Topics

A topic is a tag of scope `topic` (a global catalogue, nested like the other tags): what a
document is about with its contact, "Arbeit" or "Versicherung › Krankenversicherung" at an
insurance group that is employer and insurer at once.

- **A contact enables topics** (`Contact.topic_ids`, table `contact_topics`; admins, at most
  100). A topic and one below it may both be enabled. Disabling one is refused (`409`, naming
  it) while documents of that contact carry it; identifiers that point to it lose their topic.
- **An identifier** of a contact may point to one topic the contact enables
  (`contact_identifiers.topic_id`, checked by the contact). Found in a document, it is hard
  evidence for the pair of contact and topic. Training learns an identifier's topic only if
  all confirmed documents it stands in carry the same one.
- **A document carries one topic at most** (`documents.topic_id`), one its contact enables
  (`_access.checked_changes`). Another contact keeps it if it enables it, else it is cleared;
  without a contact there is no topic (`422`). An admin who gives a topic the contact does not
  enable enables it there in the same transaction; anyone else gets `422`. A topic cleared
  that way is no decision of the person's: change rules may set another one. A rule that sets
  another contact clears a topic it does not enable too, unless a person chose the topic: then
  the rule's contact is overruled.
- **Assignment.** An `auto` topic is proposed and set by the classification, a `manual` one
  only by a person or a rule. Topics are shown at the document by default (a square chip).
- **Filters, counts and deleting** work as for document tags: a topic finds the documents with
  it or one below it, counts each document once, and is deleted only without topics below it
  and while no document, contact, identifier or rule uses it (`409`). `topic_id` repeats in the
  list and the search: as a document has one topic, several mean one of them, each with the
  topics below it.

## Understanding

Four signals propose, the judge decides contact, topic, document type, tags, document date
and the space, the fields node reads the fields of the decided type and the title
(`core/services/classification`, the rules in `core/domain/verdict.py`).

- **`signal_llm`**: one request to an OpenAI-compatible chat completions endpoint
  (`adapters/outbound/openai_compat`, `LEKTO_LLM_*`, prompt `propose-6`) for sender and recipient,
  the topic (one of the automatic topics the listed contacts enable, or none; the prompt lists
  them at each of the at most 20 preselected contacts), type, tags (the automatic document
  tags), date, a title, the language, and the values of the fields of the type it chooses
  and of the global ones, each with the quoted passage and its label. The prompt describes each
  field once and lists only its key at every type it belongs to (a field may serve several
  types). With two spaces or more the uploader may file into (their personal space, the spaces
  they edit, the other active users' personal spaces), it also asks for the space: the
  prompt lists them by key (`s1`, ...), the uploader's own personal space first, shared spaces
  with their description, other users' personal spaces by their user only (what they wrote
  about theirs is not the uploader's business); the answer is a key or null. The answer must
  follow a
  JSON schema (`response_format` `json_schema`, or `json_object` for providers without schema
  support); an answer that does not fit is asked for once more, then the signal fails (red).
  Without a configured model (`LEKTO_LLM_BASE_URL` and `LEKTO_LLM_MODEL`) it abstains with "no language
  model is configured", and a person classifies. After the proposal it asks a second time on the
  same beginning (system prompt and document; prompt `facts-1`, issue #145 PR 5): the facts of
  the document with their role, each of a listed kind (no person's number, nothing the patterns
  read surely such as IBAN or VAT ID), the value as written, the quoted passage and its label. A
  provider's prompt cache serves the second request where the schema of the answer does not
  stand before the system prompt (`LEKTO_LLM_RESPONSE_FORMAT=json_object`, or a local server
  that turns the schema into a grammar); with `json_schema` at OpenAI or a Claude model the
  schemas differ and the document is paid twice. What goes wrong with this request (an unfit
  answer twice, an error, also one that would pass with time such as a rate limit) is in the
  output (`facts_error`) and never fails the signal: the document keeps the facts of the
  patterns, and asking the model again reads them. A webhook that answers `propose` reads no
  facts: there is no model call `facts` for webhooks (yet). The job of a node is held for four
  model requests in a row (`LEKTO_LLM_TIMEOUT` each).
- **The form of a request** (`StructuredRequest`, issue #145): every call to the model sends
  `messages[0]` the system prompt, the same for every call (`prompts.SYSTEM`: data, not
  instructions; one JSON object; no invented values; quotes and labels); `messages[1]` the
  document in its markers, as the person's message, never in the system prompt; `messages[2]`
  the task (the lists, the fields and what each part of the answer is); after an answer that
  does not fit, the note what was wrong, last. Calls about one document so begin alike (both
  shorten the text to `LEKTO_LLM_INPUT_BUDGET` the same way), and an endpoint that caches a
  shared beginning computes system prompt and document once. Lekto sets no cache marks: Ollama
  (while the model stays loaded) and Groq (for now its GPT-OSS models) cache by themselves; for
  Anthropic a LiteLLM proxy sets them (`cache_control_injection_points` with `index: 1`, the
  document, which also covers the system prompt before it; by `role: user` every user message
  would get a mark, the task and a retry too, and each call would write the cache anew).
  Some providers put a `response_format` schema before the system prompt (OpenAI; Claude behaves
  alike), and Lekto's schema differs per document and call: there `LEKTO_LLM_RESPONSE_FORMAT=json_object`
  sends the schema as a message after the task instead, and the beginning is shared. The log
  names, per call, the prompt tokens the endpoint took from its cache where it reports them
  (`output.tokens[].cached`: `prompt_tokens_details.cached_tokens`, or
  `cache_read_input_tokens` through LiteLLM); the web UI shows them in the token details.
  Two limits of the form (review of #149, open with Tobi): system prompt, document and task must
  fit the model's context together (`LEKTO_LLM_INPUT_BUDGET` is the document's share, the task
  with its lists comes on top) – Ollama drops older messages whole when a prompt is too long and
  keeps the last, so the model would get the task without the document, where before the runner
  cut the one message; and an endpoint whose chat template requires the roles to alternate (some
  Gemma and Mistral templates under vLLM or llama.cpp with `--jinja`) refuses two user messages
  in a row.
- **`signal_classifier`**: TF-IDF of words and word pairs and a logistic regression per target
  (contact, topic, type, each automatic document tag, the space), trained on the confirmed
  documents (`LEKTO_CLASSIFIER`, see Classifier). The space is learned from the documents whose
  space a person decided (`space_confirmed_at`: confirmed in the inbox, moved or handed over,
  chosen on upload, taken over), also those whose metadata nobody confirmed (they teach only the
  space); every user's personal space is one class, the uploader's own. Its spaces are the
  uploader's candidates only; if those hold at least half of the probability, it is spread over
  them. It abstains without a trained model.
- **`signal_neighbours`**: the `LEKTO_NEIGHBOURS` most similar confirmed documents the uploader
  may read (it abstains when the uploader's account is gone or deactivated), by the vector of
  the start of the text against the search index; their contact, topic, type and automatic
  document tags come from the database, and their space if a person decided it and the
  uploader may file there (one in its own uploader's personal space votes for this uploader's
  personal space). It abstains without embeddings or index. The log, the
  review and the inbox show an editor of the document's space (or who received it) only the
  similar documents they may read themselves, and what the uploader's documents carry
  (`known`) only to admins.
- **`signal_facts`**: names and aliases of contacts standing whole in the text, identifiers of
  contacts (IBAN, VAT ID, customer number, personnel number, mail domain) with the topic they
  point to, unknown IBANs and VAT IDs. A personnel number stands after its label
  (`Personalnummer`, `Pers.-Nr.`, `Mitarbeiternummer`, `Employee ID`, ...) and is kept
  without leading zeros. Each kind of identifier is a module of `core/domain/identifiers`
  (`IdentifierType`: whose it is, whether it may name a user, its comparable form, its
  patterns in a text, how a value of it is written); the registry lists them (`TYPES`, in the
  OpenAPI document as `x-identifier-kinds`). Readers deliver candidates (`Candidate`: the
  patterns in the text, a GiroCode's IBAN), checked against their kind and weighed together
  (`identifiers_from`), so another reader, a language model, would fit in. It also reads the bar and QR codes on the archive's pages, once (`documents/<id>/codes.json`; the
  OCR node deletes it with a new archive, a reprocessing from the judge takes it): an
  identifier in a code counts as one in the text, the payee of a GiroCode as a name in the
  text, which proposes nothing alone. Reading the codes may fail; the signal warns and goes on
  without them. The identifiers the document shows are its facts (`document_facts`, issue
  #145, `domain.document_facts`): kind and normalised value, the role (`contact`, `target`,
  `own`, `thread`, `refers`, `person`; the role of the kind unless the language model read the
  fact), where it comes from (`pattern`, `code`, `model`, `person`), as written and
  where it stands first in the text (reading order), and whether a person decided it. A run of
  the signal replaces the facts found before; a person's decision stays. The facts the language
  model read are checked as a field's value is: of a kind and in a role it was asked for, a
  value of the kind standing in the text, a quoted passage of the text that shows it (for the
  day of a letter, one that names the letter), and none of a person's numbers under whatever
  kind (the person's kinds in the text, the users' profiles); a fact of the same kind and value
  as a pattern's is one fact with both origins, in the model's role (a reminder's
  "Rechnungsnummer" of the invoice it reminds of is `refers`). The two signals run side by side:
  whichever stores its result last keeps both readers' facts (`kept_facts`: the facts signal
  takes the model's from the log, the model's signal the codes already kept; one lock per
  document), and names how many of the model's it took and those it refused with why
  (`read_facts`). The facts tell on the
  confirmed documents of how many contacts an identifier stands; `GET /documents/{id}/facts`
  names each identifier's `role` and `origins`. Revision 0047 takes over the rows of
  `document_identifiers` (role of their kind, origin `pattern`).
- **A person's decisions about facts** (issue #145 PR 6, `services/fact_decisions.py`,
  `POST /documents/{id}/facts/decisions`): editors of the document's space and admins add a
  fact the sources did not find, correct its value or role, reject it (it is no fact of the
  document) or withdraw a decision; the kinds that are a person's alone (tax ID, social
  security and health insurance number, e-mail address, child benefit number) only admins. A
  corrected value is two decisions: the old value rejected, the new one corrected, so a run
  that finds the old one again does not bring it back. Decisions outlast new runs of the facts
  signal; a rejected fact is no evidence of a contact for it either, and training learns no
  identifier from it (one a person added or corrected it does learn). Withdrawn, a fact is as
  the sources find it now (its role too), one only a person gave goes. An admin who corrects a
  contact's kind may correct it at the document's contact too (`at_contact`): the old value is
  rejected there, the new one takes its place, entered by hand, or learned with the same spaces
  and user where the old one was learned (who saw the old one sees the new one, #82). The first
  decision about a document's facts is a verdict on them (`field_verdicts`, field `facts`):
  corrected or added, early before the first run stopped; confirming a document with facts in
  the inbox takes them. The facts report says whether the caller decides (`editable`) and
  whether the document keeps an identifier as a fact (`kept`), lists the rejected numbers too,
  and the kept facts the identifiers do not show (`decided`: for admins all, a found tax ID as
  well; for others those a person decided, none of a person's); each fact names its `state`. The API document names each kind's role
  until a source tells (`x-fact-roles`).
- **Relations between documents** (issue #145 PR 9, `domain/relations.py`,
  `services/relations.py`, `GET`/`POST /documents/{id}/relations`,
  `DELETE /documents/{id}/relations/{other_id}`; `.idea/bezuege.md`): a document refers to
  another ("bezieht sich auf": the correction to the original, the reminder to the invoice, the
  invoice to the contract), many to many and without a kind of its own; the document types at
  both ends tell what it means. A relation points from the newer document to the older (by their
  document dates, else when they came in), so it is set from either end; a date set or changed
  later turns it (the pair is stored once, its direction read from the dates now). It is set (by a person
  or, sure, by Lekto) or suggested (Lekto was unsure; a person accepts or rejects it) and never
  makes a document yellow; a rejected suggestion stays as rejected and is not suggested again,
  a person's relation that is removed goes. Only who reads both documents sees a relation; who
  edits the newer and reads the older sets, accepts or removes it (`changeable` on each). Each
  names its `origin` and Lekto's `evidence` (the fact, the period). The first decision about a
  document's relations is a verdict (`field_verdicts`, field `relations`, at the newer one):
  added, accepted or corrected, early before the first run stopped. No events go out for
  relations yet. MCP's `get_document` lists the relations the caller sees; MCP sets none (an
  assistant reads text from outside, an instruction there could relate documents unnoticed).
  Revision 0048 adds the table `document_relations`. An admin marks a document type as a
  relation target (`relation_target` at `/document-types`, revision 0049; the switch
  "Bezugsziel" in its dialog): a contract or customer number a document shares connects it only
  with documents of such a type (a contract, a policy); without it, such a number connects no
  documents, as it would connect every invoice with every other.
- **Recognising relations** (issue #145 PR 11, `services/relating.py`, node `relate` between
  `fields` and `apply_rules`, revision 0050): in both directions, a number the document refers
  to ("Ihre Rechnung Nr. 4711", role `refers`) as another document's own (invoice, credit note,
  order number); a contract, policy or customer number shared with a document of a relation
  target's type (and, for such a document, the documents that share its number); the same
  contact, type and period (a field of type period) at another document date, unless their
  personnel, customer, contract or a person's numbers differ (two people's payslips); the day of a letter it
  answers (`letter_date`) as the date of a document of the same contact. One document of the
  same contact sets the relation, several (or one without a contact) are suggestions, another
  contact's none (a document with a contact looks only among its contact's documents). Two
  relation targets are never related by a customer number, by a contract number only as a
  suggestion. A pair a person decided stays; a suggestion of Lekto's becomes set when a source
  is sure now, and a relation of Lekto's no person decided goes when no source finds it any
  more (a contact corrected since). The node never makes a document yellow; its log names
  the relations it made (`relate-1`). Outside processing a job (`pipeline.relate`) finds them
  again after a person decided the contact, type, date, fields or facts or confirmed the
  document, and `lekto relate` queues it for every document not being processed (after the
  update to this version, and after marking a relation target). The rules see the set
  relations to documents the rule's author may read (condition `relation`), and confirming a
  document with relations Lekto set takes them (`field_verdicts`; a suggestion stays the
  person's to decide). Lekto relates across spaces; only who reads both ends sees one, in the
  relations and in the log of `relate`. Every change of relations, Lekto's or a person's, holds
  one lock.
- **Series and the documents expected next** (issue #145 PR 12, `domain/series.py`,
  `services/expected.py`, `GET /expected`, MCP `list_expected`; `.idea/bezuege.md` decisions
  10–12): documents of one contact and type, and of one contract or customer number where they
  show one (by value, whatever its kind; a document whose number was not read joins the only
  numbered series of its contact and type; a person's number names none), at least three with
  a document date at a steady interval. The interval is the median gap, as a calendar step where
  it is one (weekly to yearly; month ends stay month ends), else in days (at most 60, four
  documents, kept exactly). A gap of several steps is missed documents, a one-off within a step
  is set aside (both only a few); the spread is how far a document came off its step, against
  the one before or the rhythm (at least 2 days; in a longer history the worst step aside); a
  spread over a third of the step (a fifth for three documents) makes no series. Two documents
  of one day or one period (a correction) count once. The next document is expected one step after the last
  (with the next period where the series carries one), overdue once its spread is over, and the
  series has ended after two missed dates, today as it is in `tz`. Derived on each call over the
  documents the caller reads (`all_users`: an admin's, every user's), nothing stored, no events;
  MCP lists the ended ones only with `include_ended`. The web UI shows
  them under "Erwartet": overdue, next 30 days, later, ended.
- **The kinds of facts** (`IdentifierKind`, issue #145 PR 4; one module per kind in
  `domain/identifiers`): besides IBAN, VAT ID, customer and personnel number, e-mail domain and
  a person's numbers, those that point to the contact (creditor ID with its check digits,
  commercial register number `HRB 12345` anywhere, a company's tax number), to what a series
  refers to (contract, policy, membership, meter, loan number, mandate reference, licence plate;
  a contact's, which may name a user), mark the document (invoice, credit note, order number),
  join a strand (file reference, "Unser Zeichen", claim, ticket number), refer to a document
  ("Ihr Zeichen", the day of the addressee's letter "Ihr Schreiben vom 18.06.2026" as
  `letter_date`), point to a person (child benefit number). Each is found after its labels
  (German and English); a number written after "Ihr", "Ihre" or "your" ("Ihre Rechnung Nr.
  4711") refers to another's document (role `refers`). The customer number lost the labels of
  contracts, policies and memberships; a contact's customer number still matches those kinds
  with its value, and an admin may change its kind in the contact dialog. A value that does not
  fit a kind is refused with `not_of_kind`. The facts report lists the document's numbers that
  are no contact's or person's identifier (`numbers`). It also finds
  persons (`persons`: user id, strength, kinds of evidence, never the values): one of their
  own identifiers, or a contact's customer or personnel number that names them, is `hard`;
  their birth date in the text `medium`; their display name or an alias `weak` (an address
  block names a whole household). Only active users are found, also by a contact's number. A
  tax ID stands after its label (`Steuer-ID`, `IdNr.`, `Identifikationsnummer (IdNr.)`) or in
  its groups (`12 345 678 901`), a social security number anywhere, a health insurance number
  after its label (`Versichertennummer`, `Krankenversicherungsnummer`); a customer or personnel
  number that is one of these, stands in one or overlaps it is none (a pension fund writes
  "Versicherungsnummer: 65 170839 J 003"). A person's own numbers, a user's IBAN among them, are
  no unknown identifiers. The judge weighs the persons for the space (below), and adds the
  model's recipient: every user whose display name or alias stands whole in it, else one whose
  name matches it from `LEKTO_CONFIDENCE_THRESHOLD` on, unless another user's name matches it
  nearly as well (within 0.05, as for contacts), is `medium` (never their
  username; nothing of a profile goes to the model). The judge's entry keeps the persons it
  weighed (`persons`: user id, strength, and `public`: the strength of what anyone may know,
  their display name in the text or as the recipient). What is private about a person found
  them only for admins and that person: the log, the review and the facts show anyone else a
  user only where the text has their display name (`weak`, or `medium` as the recipient), and
  `unseen_by` names another user only for a public `medium`; their numbers then show as unknown
  identifiers. Inherent, and accepted: a suggestion to hand a document over to Anna tells its
  uploader that something in it is Anna's.

A signal *names* a value it is sure of: the model, a contact whose name or alias its sender
matches at least `LEKTO_CONFIDENCE_THRESHOLD` (legal forms and punctuation aside) with no other
close, or a type or tag of the lists; the classifier, its best class from
`LEKTO_CLASSIFIER_THRESHOLD` on; the neighbours, a value at least two and more than half of them
carry, a contact only if no other contact is carried by two of them as well (neighbours split
between senders are alike by their form, a pay slip's employee for one, and name no sender). A
signal naming another value contradicts: always yellow, with every candidate and its
sources. For a contact the classifier and the neighbours contradict only when a proof of their
contact stands in the text (its name, an alias or an identifier): similar pay slips from the
uploader's employer do not stand against the new employer whose personnel number and name the
text shows. The model always contradicts. The web UI marks a candidate as contradicted only if
a signal names it. The judge's rule:

| Field | Green (no contradiction) | Otherwise |
| --- | --- | --- |
| Contact | hard evidence (its identifier, or its name or alias in the text) and a signal names it; or the model's sender matches it from `LEKTO_CONTACT_SUGGEST_THRESHOLD` on and the classifier or the neighbours name it. Never the model's recipient | yellow with ranked candidates; an identifier alone is a suggestion; an unknown sender a new contact (an admin creates it) |
| Topic (an automatic one the decided contact enables) | the contact is green, no signal or identifier names another topic, and an identifier of the pair stands in the text and a signal names it, or two signals name it | a suggestion, always under a contact that is only suggested; signals or identifiers naming different topics leave it empty with all candidates; a topic never makes a document yellow, and another contact clears one it does not enable |
| Document type | two signals name it, or only the model and no other signal covers it (the classifier was not trained on it, no confirmed document carries it) | yellow; a type outside the list is proposed as new |
| Tags (automatic document tags; one set by hand is never proposed) | set as a type is green, without the parent of a tag set | a suggestion (ids); tags never make a document yellow |
| Document date | a valid date that appears in the text, in a quoted passage that shows it (`31.03.2026`, `31.3.26`, `2026-03-31`, `31. März 2026`, `March 31, 2026`, ...) | suggested |
| Space (among the uploader's candidates; only with two or more) | sure as a type: two signals name it, or only the model and no other signal covers it. The space it lies in: nothing changes (no model value, so rules file it as they would). One that shows the document to no one new, keeps it with its uploader and is no one else's personal space: it moves there. One with new readers, one its uploader would not see, or another user's personal space (a hand-over): yellow with the space as suggestion ("suggests another space, which shows it to more people", "suggests handing it over into another user's personal space"); more visibility and a hand-over only with a person's click. Reasons and candidates name no space and no person (the editors of the document may not see them; the web names what its viewer sees). A space a person decided is left. The persons the document names (its uploader aside) weigh in: hard evidence backs the one space whose members are exactly those it names (one other person alone: their personal space; else the one smallest space with all of them), with a signal naming it it is sure; hard evidence against a sure space, or against the one it lies in while unsure, makes it yellow with the backed space as suggestion ("names someone who would not see it there; ..."), unless the space it lies in shows it to all of them: then it stays. Medium evidence only warns: `unseen_by` lists who is named but would not see it where the check leads. Weak evidence only breaks ties among spaces the signals name equally. Persons never move a document by themselves | it stays where it is, never yellow (the best candidate is kept in the log); hard evidence of others it does not show it to leaves a warning (`unseen_by`) |

Without the model's proposal the judge is uncertain; it fails (red) only if the model answered
and no signal recognised anything.

The fields node reads the fields of the decided type and the global ones. If the model asked
for the type the judge decided, its values are taken over; otherwise (after a type correction,
or for a document from before the signals) it asks the model for the missing ones (prompt
`extract-6`, the same system prompt and document as the signal's, its own task). Each field is required or optional per type it is assigned to, a global one by its
own switch:

| Field | Check | Not passed |
| --- | --- | --- |
| Required field | its value is found and passes | yellow |
| Optional field | no value is fine (left empty); a value given must pass | yellow |
| Set by hand (`assignment: manual`) | never asked of the model; its value stays as the document has it; required, it needs a value a person or a rule set (checked by `apply_rules`, after the rules; confirming without a value is no decision) | yellow until a person enters it |
| Amounts, numbers | read as written (`2.111,68 €`, `1,234.56`, `-12,50`; an ambiguous one as the text shows it, else in the document's language) and found in the text; the currency shown as code, sign or word, or, where the text shows none at all (a pay slip's bare numbers), `LEKTO_DEFAULT_CURRENCY` | |
| Dates | as the document date; a date field must differ from the document date | the date is suggested |
| Periods | read as written (`September 2026`, `09/2026`, `KW 38/2026`, `Q3 2026`, `2025`, `01.09.–30.09.2026`, `1. bis 30. September 2026`, a date as that day) or as `{start, end}`; plausible as a date; the quoted passage shows it as written or by its first and last day; of a value, the reading no other one holds counts (two are none) | without a year (it takes the document date's), or a single day equal to the document date: suggested |
| Text, link, choice, yes/no | the value, or the quoted passage, appears in the text (`ja`/`nein` read as yes or no) | |

The quoted passage must appear in the text as well, and for an amount, number, date, text,
link or period it must show the value itself: elsewhere in the text the same digits may stand for
anything, on a broken scan a lone fragment. An amount counts in the quote only as an amount,
with decimal places or a currency beside it (`620,00`, `620 €`, `620,-`; a bare `620` is none).
Without such a quote the value is only suggested. So is a value the OCR did not read sure,
which takes two conditions; the document date follows the same rules:

- **The value's place is not poorly read, counting content only.** Where the value's words
  are found on the page (see the next condition), its place is the 20 content words nearest to
  them, its own words not counted; it counts as poorly read from three of them unsure (15 %:
  among 20 words one stray reading is already 5 %; the page keeps
  `LEKTO_POOR_READING_THRESHOLD`)
  (`'Betrag': the text around the value was poorly read (3 of 20 content words unsure)`): on a
  broken scan a number may be anything, however sure Tesseract was of it. No layout is
  assumed, neither blocks nor tables: nearness is the gap between the words' boxes, Euclidean
  between their nearest edges, the vertical gap in line heights (the content's median hOCR
  `x_size`, without sizes its median box height) and the horizontal one in characters (the
  median width of one in the content's boxes) at half a line each, about the width of a
  character for its font size; equal gaps (to a millionth of a line) go by reading order. So
  the next word on the line is usually nearer than the line below, and a word two lines down
  is about as far as one three characters' gap away on the same line. The page's shape does
  not count: line and character are measured on the page itself, a receipt like a letter.
  A quote without a place (its words are not one run of the page's text layer, or the model
  put it together) leaves the value itself to be found among Tesseract's words: where it
  stands just once on the pages, its words decide as with a place. With fewer than 20 other
  content words on the page, without the value's words (no words were kept, the words do not
  show the value as written, the value stands more than once without a place), and for what
  the vision language model read, the place is the page: of the value's quote, or
  any recognised page if the quote was not found, poorly read from the same share of unsure
  content words with at least ten of them. Where the quote stands more than once on a page
  and the value's words are found at one place, their surroundings stand for that page.
  Noise counts neither as a word nor as unsure: a
  word with fewer than half of its characters letters or digits (rules, marks), a dot, dash or
  underscore leader (`Datum..........`), also one Tesseract read as letters (`«oso:`, `see`,
  `EEE`: a box under 35 % of its line's height, where a word of small letters still has the
  x-height), one or two characters without a digit (stray marks read as `gy`, `TI`, `j`), a
  word right beside a leader on its line, within a line's height (Tesseract reads a clean
  label beside its dots unsure, `Krankenkasse` at 38 %), and the words of a line under 60 % of the page's typical line height (hOCR `x_size`, the median
  over the words: a letterhead's small print; lines of the body font lie up to a fifth apart,
  footnotes stay content). On the pay slip that led to the rule, 10 % of all words were
  unsure, almost all of them leaders, letterhead and marks; on a synthetic scan shaped like it
  (`tests/scans.py`), 2 % of the content. Its table of amounts was also read badly: 9 % of the
  page's content words were unsure, none of the 17 in the header with its date. On a
  synthetic scan like that (`BAD_TABLE`), the 20 words around the date are all sure and keep
  it green, while an amount inside the table is only suggested.
- **The value itself was read sure.** Every word Tesseract read that makes up the value within
  its quote's boxes needs 60 % confidence or more (the shortest runs of the words there that
  show the value, read as the quote check reads it; a currency counts where the amount needs it
  to be one): a date at 96 % passes, an amount at 32 % is
  only suggested (`'Betrag': the value was read unsure (32%)`). Where these words cannot be
  found, this condition does not apply, and neither does it for the vision language model,
  which gives no confidences: its pages count all words, with what it marks unreadable as
  unsure.

Tesseract is sure of some misreadings, so a poorly read place still makes every value in it a
suggestion. A document recognised before content was counted keeps the rule of all words on
its pages (its log entry has no content counts and no `reading.json` exists) until it is
reprocessed from `ocr`. One read with `reading.json` gets the rule of the surroundings when it
is reprocessed from any node after `ocr` (such as `judge` or `fields`): the judge and the
fields node read the kept words on each run, without reading the scan again.

A field's description (up to 300 characters) goes into both prompts after its name and
choices: it tells the model what belongs
in the field, whose name is often an internal one no document shows (`LA_Brutto`: the month's
gross total, not the base salary). The model is told to copy the quoted passage exactly as it
stands, numbers unchanged, and where the label and the value stand apart (a table, a form with
boxes), the line the value stands on; the check stays strict.

The model also gives each field value's label as it stands in the document (`label`,
`Gesamtbrutto`, or null), and the fields node checks whether the value stands by it
(`core/domain/labels.py`; issue #55, step 1: **recorded, not enforced**, it changes no outcome,
lane or reason). Only amounts, numbers, dates and periods are checked, the values a pay slip or
a form lists among others of their kind, where the quote of the wrong line passes every check
above. The label is looked for among the words of the parsed text (`content.json`, which every
document has, digital or scanned), as quotes are located, but as whole words: case and spacing
evened out, then on letters and digits alone (`Brutto` is not in `Steuerbrutto`; `Gesamtbrutto`
is in `**Gesamtbrutto:**`). A label over two lines is measured by the line it ends on. The value's words are those at its quote's place that show it, or,
where it has none, where the value stands just once on the pages. The value stands by its label
on the label's line to its right, or below it in its column (overlapping it, or starting within
four characters of its left edge) within three lines (`LABEL_LINES`); the line (the usual
distance between the page's lines) and the character (the median width of one) are measured on
the page itself. Where the label stands more than once, any place with the value by it passes.
The outcome goes into the field's check (`label`: `text` and `outcome`, in the processing log,
`FieldCheckOut.label` of the review and the inbox, and a line of the fields node in the web
UI's log): `beside`, `apart` (the label stands in the text, the value not by it),
`label_missing`, `no_label` (the model gave none) or `unknown` (no words with boxes, the value
not found or not just once, or a type that is not checked). A field the model gave no value for
has none. An answer without labels (to `propose-3` or `extract-4`) still reads, as without
them, and a label that is no text counts as none. A failure of the check (a store that cannot
be read, an error in it) leaves the labels unknown or out and never fails the node. The evaluation counts the outcomes per case and in total.

The title is the model's while the document still has its file name or the title the machine
gave it; a rule replaces the machine's title without making the document yellow. A document
type's title pattern is such a rule: a template (see Rules) that a global rule of the type
carries out, made, changed and deleted with the pattern and read-only otherwise
(`RuleOut.managed_by_document_type_id`, changes 409). It gives way to another rule that sets the
title (note `yielded`); a value it writes that the document lacks leaves the model's title;
confirming runs the rules again with the decided values. Every check with its
candidates and the raw answer is in the processing log (`fields`, `answer`), so a proposal stays
traceable after a correction; the rules read them with `core.services.inbox.field_checks`.

The document text is sent between markers derived from its hash, and the model is told to treat
it as data. It can only answer with the fixed schema: there is no field for spaces, users,
members or actions, and additional fields make the answer unfit. Long documents are shortened to
`LEKTO_LLM_INPUT_BUDGET` characters, a run of spaces counted once (the columns of the text as it
is set cost a model little; beginning and end kept, the middle left out); with many
tags, at most `LEKTO_LLM_MAX_TAGS` are listed, those named in the text first; of the contacts,
the 20 the text names most (with their aliases).

**Privacy.** The shortened document text, the names of document types, tags and fields, the
descriptions of types and fields, and the names of the contacts the text names go to the
endpoint in `LEKTO_LLM_BASE_URL`; the file, other contacts and users do not. Every log entry of the two model nodes names the endpoint host and
the model. At start, a warning names every
configured model endpoint outside the local network (not loopback, private, link-local or a
local name), because document content leaves the system there.

**Ollama.** `LEKTO_LLM_BASE_URL=http://<host>:11434/v1` (with `/v1`). Ollama does not take a
context size over this API and cuts longer prompts silently (often at 4,096 tokens); start it
with `OLLAMA_CONTEXT_LENGTH=8192` or more. Local models on a CPU are slow:
`LEKTO_LLM_TIMEOUT` is per request, and the job lease allows twice that (one repeated request).

**Classifier.** One model for all users (`core/services/classifier.py`,
`adapters/outbound/sklearn`). Training examples are the documents whose metadata a person set or
confirmed (`confirmed_at`: confirming in the inbox, changing contact, type, topic, tags, date or
fields, taking a document over); green documents do not train. The space is learned from the
documents whose space a person decided (`space_confirmed_at`), as the label `own` when it is
the uploader's personal space; such a document whose metadata nobody confirmed teaches only the
space (contact, type, topic and tags learn from confirmed documents alone). A change that only adds or
removes tags set by hand (statuses such as "to pay") confirms nothing: they say nothing about
contact and type (`documents.confirms`); with an automatic tag or any other confirming value
it confirms. A recurring job (`classifier.check`,
every ten minutes) queues the training (`classifier.train`, which may take an hour before another
worker takes it over) once `LEKTO_CLASSIFIER_MIN_EXAMPLES`
documents are confirmed (or placed by a person) and no model exists, or
`LEKTO_CLASSIFIER_RETRAIN_AFTER` were confirmed or placed since the last one; `lekto train` and `POST /classifier/train` train at
once. Training also learns identifiers of contacts: one that stands in at least two confirmed
documents, all of one contact (the household's own IBAN stands on letters of many and is never
learned); a learned identifier an admin rejected, or its user declined, stays rejected. A learned
identifier keeps the spaces of its documents (`contact_identifiers.learned_in`): only their
members see it (the pay slips in a personal space teach the employer a number its user alone
sees). A learned customer or personnel number belongs to a user when every one of its documents
is surely theirs alone: in their personal space, or naming them by more than their name (one of
their numbers, a number entered by hand that names them, their birth date). The model is stored as `npz`
without pickle (`classifier/model-<n>.npz`, the files of the latest three are kept; every model's row stays, for the history of its accuracy) and predicted with numpy
alone, so a new scikit-learn version cannot break it. It sees about the first 8,000 and the last
4,000 characters of a longer text, a run of spaces counted once (12,000 in all, `TEXT_LIMIT`).
`GET /classifier` tells its state to every user (the page "System"), `GET /classifier/models`
what every model learned and how well, oldest first; training on request is for admins.

**After the update to 0.2.** Three things, in this order:

1. The search index gets the attribute `confirmed` the neighbours filter on. The migration
   raises the version of every confirmed document, so the worker's reconciliation at its start
   writes them again; vectors of unchanged text are kept, so this needs no embedding calls and
   no `reindex` (which would embed every document anew). Until it is through, the neighbours
   find fewer documents. Documents taken over before count as confirmed; the first training
   starts by itself once the worker runs. The same reconciliation writes every entry in the
   index's layout 2 (fields with a value, the title's sort key, periods in ISO), with the
   vectors it has.
2. 0.2 reads the text as it is set instead of Docling's Markdown. A document parsed before
   keeps its Markdown, which is read meanwhile, until `lekto reparse` (or
   `POST /pipeline/reparse`) has the worker read its text again; nodes, lane and metadata stay
   as they are. The search index then takes up the new texts, which embeds every document anew
   (with an embedding service elsewhere this takes a while: choose the time), and the
   classifier is trained on the new texts afterwards (`train`).
3. 0.2 reads the bar and QR codes on the pages. `lekto read-codes` has
   the worker read them for the documents from before and keep the identifiers each document
   shows (`document_facts`, until 0047 `document_identifiers`), so that the warning when attaching an identifier counts
   every confirmed document. It reads locally and sends nothing out; nodes, lane and metadata
   stay as they are. Documents taken over get their codes only this way: the signals abstain
   for them. Run it once `reparse` is through, which changes the text the identifiers are read
   from.
4. The node `relate` (issue #145) finds the relations of new documents; documents from before
   have it skipped. `lekto relate` has the worker find theirs; run it after `read-codes`, and
   again after marking a document type as a relation target.

**After the update to 0.3.** Revisions 0024 to 0029 run at start; then four things:

1. "Drawer" is "space" everywhere, a break of the API: `/api/v1/spaces`, `space_id` (documents,
   upload, move, confirm, filters), the rule action `set_space`, the template variable
   `{{ space }}`. Revision 0024 rewrites what is stored (rule actions, the variable in rule
   templates and title patterns, open `document.filed` events, the processing log); a template
   that already uses `space` for something else stops it, and says which (rename it there
   first). A client that still sends `drawer_id` on upload files into the default space.
2. The worker's reconciliation at its start writes every entry in the index's layout 5 (the
   space, tags with their ancestors, the groups of contact and type, the topic), with the
   vectors it has: no embedding calls and no `reindex`. Until it is through, the search of
   other users misses documents in spaces they read.
3. Tags and fields from before are automatic document tags at the top level, shown on the
   document, and automatic fields. Mark status tags such as "to pay" "by hand only": the
   classification then never proposes them, and changing them alone confirms no document. Nest
   tags, put contacts and types into groups, enable topics at contacts and give identifiers
   their topic; the training learns topics (of documents and of learned identifiers) with its
   next run (`train` trains at once).
4. Logos of contacts come by upload. Fetching them from the contacts' websites is off: with
   `LEKTO_LOGO_FETCH=true` a contact without a logo that gets a domain has it fetched, and
   `lekto fetch-logos` fetches them for the contacts from before
   (outgoing HTTPS to their domains only).

**After the update to 0.4.** Revision 0030 runs at start. Nothing is new then: the documents
from before stand in an inbox only while they are processed, yellow or red, and a run that
started before the update makes no document new unless it is its first. `GET /inbox` lists
everything open, not only yellow and red documents: a client that wants those asks for
`tab=review` or `tab=intervene`. Documents taken over from Paperless-ngx with their metadata
(`migration`) are not new: the metadata are a person's (see Inbox).

**After the update to 0.5.** The project is called Lekto now, not Papiq: variables, cookies,
search index, SQLite file and classifier format have new names, and nothing reads the old ones.
The steps are in [deploy/README.md](../deploy/README.md) ("Upgrading from Papiq").

Rights hang on spaces alone (a break of the API). Revisions 0033 and 0034 run at start:

1. Every user's default space becomes their personal space (`personal_of`, stored name
   "Personal"; a user without one gets one). The owner of every other space becomes an
   editor of it, a share `read` a reader, a share `read_write` an editor
   (`PUT/DELETE /spaces/{id}/members/{user_id}` replace the shares). Spaces of several owners
   with the same name keep the oldest's; the others get " (username)", shortened to fit and
   never a name another space keeps. Former sharers with `read_write`, editors now, find no
   old document new in their inbox (their marks are silent: not under done either).
2. A document's owner becomes who uploaded it (`uploaded_by`), information only. Every file
   exists once per installation now: the original is unique, no longer per owner. If two
   owners hold the same file, the revision stops at the new index; delete one of them first.
3. A user rule becomes a rule of its owner's personal space (`scope` `space`, `space_id`);
   `{{ owner }}` in rule templates and title patterns becomes `{{ uploaded_by }}` (a template
   that uses `uploaded_by` otherwise stops the revision). Global rules may do everything now.
   Every rule version names the space of its rule (`rule_versions.space_id`), since a rule may
   move.
4. The worker's reconciliation writes every entry in the index's layout 6 (no owner), with
   the vectors it has. Until it is through, the search filters entries of layout 5 by space
   only: an editor misses nothing, a document whose owner is no member of its space stays
   hidden from that owner.
5. Revision 0034: spaces get a description (for the language model), documents the time a
   person last decided their space (`space_confirmed_at`): a confirmed or taken-over document
   has it from `confirmed_at`, one a person moved or placed on upload from the latest such
   log entry; every other document's space is undecided. The classifier learns the space with
   its next training (`lekto train`, or after `LEKTO_CLASSIFIER_RETRAIN_AFTER` decisions);
   until then the language model alone suggests spaces where the other signals know none.

The downgrade restores owners and shares where the data allow (a personal space becomes the
default space, any other space belongs to its oldest editor, a document to who uploaded it
while they are a member of its space, a space rule is a user rule again). It stops where 0.4
could not load the data: a shared personal space, a global rule that does more than tag, set
fields and force a review.

Revision 0035 adds display names (`users.display_name`, unique through `display_name_key`) and
the profiles (`user_profiles`, `user_aliases` (unique per user only), `user_identifiers`), and
lets a contact's identifier name a user (`contact_identifiers.user_id`; until revision 0040 set
to null with the user). Nothing is filled in: users are shown by their username until they or an admin enter a
display name (settings, user management), a migration fills them from Paperless. Once a user has
one, `{{ uploaded_by }}` in titles and paths renders it instead of the username: titles and
paths rendered anew change.

Revision 0036 adds the lane of a document's first run (`documents.first_lane`). It reads it back
for the documents already there: a document whose first run stopped has its lane, one that ran
again what the log of its first run tells (filing green, whatever else the run logged, as
filing runs only when nothing before it is uncertain or failed; otherwise a failed node red, an
uncertain result yellow; entries of a person or a change and a text read again aside); where the
log tells nothing, and for a document still in its first run, it stays null.

Revision 0040 (issue #82) adds the spaces a learned identifier was learned in
(`contact_identifiers.learned_in`) and lets a user's numbers at contacts go with the user
(`contact_identifiers.user_id` is `ON DELETE CASCADE`: a deleted user's number would otherwise
be everyone's to see). Identifiers learned before have no spaces: until the next training
(`lekto train`, `POST /classifier/train`) only admins see them.

Revision 0042 adds the first runs (`first_runs`) and the verdicts per field (`field_verdicts`)
and reads them back from the log as far as it tells: the first run of each document whose first
lane is known (the first entry of each node in run 1 up to the stop: filing for green, the
failed node for red, the last node for yellow); the verdicts of people on documents of the web
and the API (confirmations, changes, moves; an entered value is judged by the value the document
holds now if nothing touched the field since, else by whether it differs from before, where that
tells). Migrated documents get no verdicts: their changes are mostly the migration's alignment.

**Evaluation.** `lekto evaluate [--fake]` runs the synthetic documents in
`evaluation/` cold and trained and writes a report; see [evaluation/README.md](evaluation/README.md).

## Rules

Rules are data, not code (`core/domain/rules.py`, `rules_json.py`, `rule_conditions.py`,
`rule_planner.py`, `core/services/rules`). A rule has a name, a priority (0 to 1000, default
100, higher first), triggers, a tree of conditions and actions. Changing its content makes a new
version; old versions stay readable, so the processing log can refer to them. Enabling and
disabling make no version; deleting is a soft delete. A change may move the rule into another
space or between a space and global (`PUT` with `scope` and `space_id`): the caller changes it
where it is and edits where it goes (global: admins); every version names its space
(`space_id` in `GET /rules/{id}/versions`), so the history shows the move.

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
    {"type": "set_space", "space_id": "<space id>"},
    {"type": "add_tags", "tag_ids": ["<tag id>"]},
    {"type": "set_title", "template": "{{ contact }} {{ document_date | date: '%Y-%m' }}"}
  ]
}
```

- **Scope.** A space rule (`scope` `space`, `space_id`; default: the caller's personal space)
  belongs to a space: its editors make, read and change it, and it acts on the documents in
  that space. A global rule (admins) acts on every document. Both have every action. Everyone
  reads the global rules; space rules are read by the editors of their space and admins
  (`all_users=true`: every space's; `space_id` narrows the list to one space). On arrival the
  global rules and those of the space the document lies in run (its uploader's personal space,
  unless the upload named another).
- **Entering a space.** If rules file a document into another space, that space's own rules
  (trigger `ingest`) run next, and so on. Each space at most once in such a chain: rules that
  would file it back into a space it was in stop the chain, the move is not made and the
  document waits in the inbox ("rules move it back and forth: tobi → Haushalt → tobi"; the
  node's output lists the `spaces`). The chain goes on across a person's click: after a
  confirmation the spaces of the runs that waited for it count (the input's `chain`). A value
  a rule set only through unconfirmed model values stays unconfirmed for the next space's
  rules, so a later rule cannot file on it into a wider space without the click, and a later
  rule setting another value there is a conflict. The patterns of every rule the chain may
  meet run before the transaction. A completed document that a person moves or hands over,
  that change rules file elsewhere, or that a rule applied to existing documents files
  elsewhere, runs the target's rules the same way, but as change rules: nothing turns yellow,
  what cannot be applied is reported in a `rules:change` log entry per space (`trigger`
  `ingest`, `space_id`); after a person's move the rules leave the space they chose.
  Confirming a document into another space continues processing at `apply_rules`, where the
  target's rules run on arrival. If the rules file a document into the space the judge
  suggested, the judge's open space is settled. When the judge itself moves a document (one
  that shows it to no one new), the rules of the space it came from do not run: the document
  arrives in the judge's space.
- **Filing.** `set_space` files into a space whoever saved the rule's current version may file
  into (an editor of it, or an admin), or hands the document over into another user's
  personal space (no membership needed; a deactivated user receives nothing). If that right is
  gone, the action is refused and the document waits in the inbox (`no right to file into space
  'X' (any more)`). A space rule never moves a document that lies in another space. Applied to
  existing documents, a rule also files only where the person applying it may file (or hand
  over), whoever saved it.
- **Triggers.** `ingest`: the pipeline node `apply_rules`, when a document arrives. `change`:
  a person changed the metadata of a document whose processing is complete.
- **Conditions.** Groups `all` or `any`, each may be negated with `"not": true`; at most 5 deep
  and 50 conditions. Fields and operators:

  | Field | Operators |
  | --- | --- |
  | `contact`, `document_type` | `is`, `in`, `present`, `missing` |
  | `topic` | `is`, `in`, `present`, `missing`; a topic matches the topics below it |
  | `tags` | `contains` (has this tag), `in` (has one of), `present`, `missing`; a tag matches the tags below it |
  | `contact_group`, `document_type_group` | as `tags`, over the groups of the document's contact (type) with their ancestors |
  | `channel` (Eingangskanal: `web`, `api`, `migration`) | `is`, `in` |
  | `text` | `contains` (normalised like the classification checks), `matches` (regular expression) |
  | `document_date` | `is`, `gt`, `lt`, `present`, `missing` |
  | `field` (with `field_id`) | by data type: text and link `is`, `in`, `contains`, `matches`; number, amount, date `is`, `gt`, `lt`; yes/no `is`; choice `is`, `in`; period `is`, `overlaps` (shares a day with a period), `gt` (starts after a date), `lt` (ends before a date); all `present`, `missing` |
  | `fact` (with `fact_kind`, `fact_role` or any role; issue #145) | `present`, `missing`, `is`, `in` (the values as written, kept and compared normalised), `matches` (against each value as the text writes it, `^` and `$` at its ends); facts a person rejected do not count, and a fact condition is never unknown |
  | `relation` (issue #145) | `present` (refers to any document), `missing` (to none), `is`, `in` (to a document of one of the types); the set relations it refers by (the newer of the pair), not suggestions; never unknown |

  `matches` takes `case_sensitive` (default false). Patterns run with the `regex` package
  (`adapters/outbound/regex`) in a thread with a time limit (`LEKTO_RULES_PATTERN_TIMEOUT`); a
  pattern that times out does not match and is logged. All patterns of one run on one
  document get two seconds together, a preview page twenty; the patterns left do not match. The text is the parsed text without
  markup, at most `LEKTO_RULES_MAX_TEXT` characters; it is loaded only if a rule looks at it.
- **Actions.** `set_space`, `set_contact`, `set_topic`, `set_document_type`, `set_title`,
  `add_tags`, `remove_tags`, `set_field`, `force_review` (with a reason), `send_webhook` (see
  below). `set_topic` is for
  every rule; it is skipped (and noted) if the contact the document ends up with does not
  enable the topic. `add_tags` and `remove_tags` take document tags (also those set by hand);
  a tag above one the document keeps or gets is not added, a parent gives way to a child
  added. Saving a rule checks the scope of every tag it names (`422`).
- **Steps** (Tobi, 25.10.2026, `.idea/webhooks-und-auftraege.md`). The actions are an ordered,
  linear sequence of at most 20 steps, which may also ask a webhook and check:
  - `ask_webhook` (`name`, `webhook_id`, `timeout_seconds`, default 300, 30 to 86,400;
    `missing`, default `red`): a task through a webhook of whoever saves the rule (see
    *Tasks* under Webhooks); the node waits for the answer ("running externally"), and the
    steps after it see it as `steps.<name>`. Without an answer (none in time, an error, an
    invalid one) `red` fails the node (no rule acts), `yellow` ends the rule there (its steps
    before count) and holds the document for a person, `continue` goes on without
    `steps.<name>`. After a person decided in the run it is only reported (`steps_reported`).
    A rule with such a step runs on arrival only (`triggers: ["ingest"]`), is not applied to
    existing documents (`409`, `rule_asks_on_arrival`) and needs `LEKTO_PUBLIC_URL`. A
    confirmation in the inbox that changes nothing keeps the answers of the run before; one
    that changes something, and processing again, ask anew. Outside processing (the rules a
    space runs when a person moves a document into it) the step is not asked: the rule ends
    there.
  - `condition` (`conditions`, a group as in the head): on the document as the rule's own
    steps before left it, and on what a step brought (`{"field": "step", "path":
    "accounting.paid", "op": "is", "value": true}`; `is`, `in`, `contains`, `gt`, `lt`,
    `present`, `missing`). If it does not hold, the rule ends there; its steps before count.
  Each rule works on its own copy of the document; the actions of all rules are combined at
  the end, as before. Templates see `steps.<name>` of the steps before them that ask
  (`{{ steps.accounting.beleg }}`). The log shows each step (`steps`: a condition's `holds`,
  a question's task, status and answer).
- **Templates** (in full, with examples: [docs/templates.md](../docs/templates.md)). A title,
  a field's value given as text and a review's reason are Liquid templates (`python-liquid`,
  `adapters/outbound/liquid`): `{{ contact }}`, `{% if field.la_brutto %}`,
  filters with `|`. They see `title`, `filename`, `original_filename`, `contact`, `topic`,
  `document_type`, `document_date`, `added`, `tags` (those set), `contact_groups` and
  `document_type_groups` (the groups the contact and the type are in, by name, sorted), `space`
  (a personal space by its user's name), `uploaded_by` (who uploaded it, by display name, else username),
  `channel`, `pages` and
  `field.<key>` (`FieldOut.key`, from the name: `LA_Brutto` is `la_brutto`; an amount has
  `.amount` and `.currency`, a period `.start` and `.end`), as the rules leave the document,
  and its facts (`facts.<kind>` as written on one line, `facts.refers.<kind>`,
  `facts.girocode.*`, `fact_list`; none a person rejected, none of a person's; see
  docs/templates.md). A period writes itself in ISO 8601 by what it is (`Period.notation`): `2026-09`, `2026-W38`,
  `2026-Q3` (ISO has no short form for a quarter), `2026`, a day as `2026-09-15`, else its
  ends, `2026-09-01/2026-09-14`; `{{ field.x.start | datetime: format: 'MMMM yyyy' }}` writes
  it in words. `datetime`, `currency` and
  `decimal` format in `LEKTO_TEMPLATE_LOCALE`, an amount writes itself as `3.650,00 EUR`. A
  template sees nothing but these values (no attributes of objects, no `include`), loops stop
  after 1,000 turns and output after 10,000 characters. Writing a missing value sets nothing
  (note `skipped`); `| default` and `{% if %}` make a part optional; a forced review holds with
  its reason as written. Saving checks the syntax and the values (422, `actions[2]: unknown
  value field.brutto`); single braces (`{contact}`, as before 0.2.0) are text like any other.
  Renaming a field rewrites the templates that use it (a new version); a field a template uses
  is not deleted (409). `POST /templates/preview` checks a template and renders it with a
  document the caller may read, and gives that document's values as a template writes them
  (`values`, for the template editor's list); with `field_id` it reads the result as that
  field (`read`, `unreadable`), without a document too if the template uses no value.
- **Setting a field** (`set_field`, issue #145). Text is a template for every field type; what
  it renders is read as the type has it (`fields.read_written`): first the forms templates write
  (`1234.5`, `2026-03-14`, `2026-Q3`, `true`, an amount with or without a currency code), else
  as a person writes it (`2.111,68 €`, `14. März 2026`, `KW 38/2026`, `ja`), an ambiguous
  number as `LEKTO_TEMPLATE_LOCALE`'s language means it, an amount without currency in
  `LEKTO_DEFAULT_CURRENCY`, a two-digit year nearest to the day the document came in; a number
  or an amount has no words but a currency's, a currency code is an ISO 4217 one, a period
  without a year is not read, nor one in ISO form that names none (`2026-Q5`). What cannot be read sets nothing (note `skipped`,
  `template_unreadable`, no yellow). An amount, a period or yes/no as JSON is a fixed value;
  fixed values that are text in their JSON form (`"12.50"`, `"2026-03-31"`, a choice, a link)
  write themselves and read as before (also `.5`, `1e3`, `20260314`), and a choice's option is
  fixed even where it holds braces. Text without markup is read when the rule is saved (422 if
  it cannot be). Rules setting one field keep their order with templates; values are compared
  by what they are (`84.2` and `84.20` are one amount). A stored value that is no valid
  template blocks neither renaming nor deleting a field, and a rename rewrites only values with
  markup. Templates of fields see the fields as they were, not what other field actions set.
- **Evaluation.** All conditions see the state before any rule acts; a rule's action never makes
  another rule match in the same run. Contact, topic, type and tags the model set and no
  person confirmed are distrusted, and so are the groups of such a contact or type: a rule that
  matches only because of them does not file into a space that shows the document to someone
  new (a member the space it lies in lacks; handing it over, too); it is reported instead. Retroactively
  such a move is a conflict: it acts only where the person accepts it.
- **Combining.** A field set by one rule, or by several to the same value, is set. Different
  values are a conflict and nothing is set; priority never decides. A value a person decided
  in the current processing run is never replaced (the rule is logged as overruled): in the
  inbox, by a change, or the space chosen on upload or by moving the document; a value the model set and no person
  confirmed is not replaced either (conflict). Tags of all rules are combined; added by one and
  removed by another is a conflict. Reasons and notes name contacts, types, topics, spaces,
  tags and fields by their names and a field's value as written ("rules set different values
  ('Nord, Arbeit': 'Nord Versicherung', 'Süd': 'Süd AG')", "'Betrag': …", `12.50 EUR`,
  `2026-Q3`); the ids stay in the structured output (values, suggestions, effects), and only
  something that no longer exists is named by its id.
- **On arrival** conflicts, refused actions and forced reviews make `apply_rules` uncertain: the
  document waits in the inbox. Confirming it there (`POST /documents/{id}/confirm`, optionally
  with `space_id`, as moving) decides the open fields and continues to filing; a forced review
  the person saw counts as answered. Filing always succeeds: rights hang on the space.
- **On a change** (`PATCH /documents/{id}`) rules are edge-triggered: a rule acts only if it
  holds after the change and did not hold before. Fields the person set in this change, or
  decided before in this processing run, are not touched. Nothing turns yellow: what cannot be applied is only reported, in the `rules`
  block of the answer (to the editors). If the rules file the document where an editor who made
  the change can no longer read it, the editor's answer is only `{"id": …, "access": null}`.
  `POST /documents/{id}/dry-run` shows the same without storing anything.
- **Retroactively.** `POST /rules/{id}/apply/preview` lists the documents the current version
  would change, newest first, with changes and conflicts (a page looks at 200 documents at
  most). It plays the rule as applying does, in a unit of work it never commits: `outcome` holds
  the chain (the rules of each space the rule files the document into, and of the spaces those
  file it into, each at most once: what they do, `moved_to`, `looped_to` where the chain stops)
  and the space it ends up in; `accepted` the same with the conflicts accepted. `POST /rules/{id}/apply` pins a version and applies it to the selected documents (at
  most `LEKTO_RULES_APPLY_MAX_DOCUMENTS`) in the background, job `rules.apply`, 25 documents per
  job; conflicts only where accepted (`accept_conflicts`), forced reviews do not act. A space
  rule is applied by the editors of its space to the documents in it, a global rule by anyone to
  the documents they may edit; rights are checked again per document. Progress: `GET /rule-applications/{id}`.
- **References.** Contacts, types, tags, fields and spaces a rule names must exist (`404`),
  spaces must be ones the caller may file into, or another user's personal space (`403`).
  Deleting one of them, or removing a choice a rule uses, disables the rules that use it with
  a reason; enabling checks again for the author of the current version. A tag a rule uses is
  not deleted (`409`). Deleting a space removes its rules; deleting a user removes the rules of
  their personal space.
- **Log.** Every run is a processing log entry of node `apply_rules` with the rules and versions
  checked, matches, effects and notes. `model_version`: `rules` (the pipeline node),
  `rules:change` (after a change; it also records what the person changed), `rules:apply`
  (retroactive), `person` (a confirmation), `person:space` (a space chosen on upload or by
  moving). Later runs read from the log which values a person
  decided and which the model set.

## Search

Hybrid search in Meilisearch: full text and meaning (vectors) in one query. Without
`LEKTO_MEILISEARCH_URL` there is no search; without `LEKTO_EMBEDDING_BASE_URL` it works on words
only. `GET /api/v1/documents/search?q=…` takes the filters of `GET /documents`, `limit`,
`offset` (at most 1000 hits can be reached) and `semantic_ratio` (0 words only, 1 meaning only;
default `LEKTO_SEARCH_SEMANTIC_RATIO`). Each hit carries the document as `GET /documents/{id}`
does, a score and a snippet whose matches are marked. The answer tells how it searched
(`mode`: `hybrid`, or `words`, the fallback that always stays; `semantic` is `mode` as a flag),
and why by words alone where the meaning was to take part (`reason` with a code:
`search_no_embeddings`, `search_embed_timeout`, `search_embed_failed`,
`search_embed_dimensions`; none for `semantic_ratio=0`). An unreachable index is `503` with
`search_index_unavailable` (the list without words works on), a missing one
`search_not_configured`; what went wrong stays in the log.

- **The index follows the documents.** The indexing service subscribes to the document events
  (`search.index`) and queues a job per change, but one at a time per document: while one waits,
  further changes join it (`coalesce_key`); a change after it started queues the next. A job
  writes the document and reads it back, up to three rounds, so a change made meanwhile is not
  lost. A failed job repeats after 30 s,
  doubling up to an hour, ten times; the last attempt writes the words without vectors. Renaming
  a contact, a type or a tag, nesting a tag elsewhere and changing the groups of a contact or
  type queue the documents concerned: the index holds names for the search by words. A reconciliation compares the index with the database and queues what is
  missing, stale or gone: every `LEKTO_SEARCH_RECONCILE_INTERVAL` and at every start of a worker.
  If the embedding endpoint is down, the document is written at once with the vectors it has
  and the job repeats for the new ones. If Meilisearch loses its data, the adapter sets the
  index up again; restart the worker or call `POST /search/reindex` to fill it without waiting
  for the next reconciliation.
- **Layout of an entry.** Each entry carries the layout it was written in (`LAYOUT` in
  `core/domain/search.py`). Layout 2 adds the ids of the fields with a value (`field_ids`), the
  title's sort key and periods in ISO 8601 beside the German words (`2026-W38` and `KW 38 2026`);
  layout 3 the space instead of the drawer; layout 4 the tags with their ancestors and the groups
  of contact and type with theirs (`contact_group_ids`, `document_type_group_ids` filterable,
  their names searchable); layout 5 the topic with its ancestors (`topic_ids` filterable,
  `topics` searchable, the topic's path in the header of the first section's embedding); layout
  7 the facts (issue #145 PR 7): `facts` filterable, a token per fact not rejected by its kind,
  value and role and by each part of them (`kind|value|role`, `*` for any:
  `document_facts.fact_tokens`), and `fact_values` searchable, the values normalised (a search
  for `R20260815` finds "R-2026-0815"; a person's numbers are no words of the search). The
  reconciliation writes older entries again and keeps their vectors, since the embedded text
  does not change (no document had a topic before layout 5; the facts are not embedded): no
  embedding calls. A person's decision about a fact, and the facts `read-codes` keeps outside
  processing, are a change of the document (`document.updated` with the field `facts`): the
  index takes them in at once.
- **Sorting.** `sort` comes first among Meilisearch's ranking rules, so relevance breaks ties,
  also with vectors; document date, arrival and the title's sort key are sortable. Without
  `sort` (or with `relevance`), the hits come by relevance.
- **Rebuild at any time.** `POST /search/reindex` (admins) or `lekto reindex` builds
  `<index>-rebuild` from the database and the object store, 50 documents per request, while the
  active index keeps serving, swaps it in and reconciles what changed meanwhile. The index holds
  no information that is not in the database.
- **State.** `GET /search/status` (every user, the page "System") counts the documents of the
  database and of the index, those with vectors and the vectors (`SearchIndex.stats`, from
  Meilisearch's index stats), the index jobs running and waiting with an estimate of when they
  are through (from the index jobs done in the last ten minutes), and how long index jobs ran
  with and without embedding (from the latest 2000 done within `LEKTO_RETENTION`, counted at
  most once a minute per API process): an index job reports the sections it embedded
  (`{"sections": n}` in its result) and whether it wrote without vectors because the embedding
  failed (`"embedding_failed": true`; such a job measures neither kind). `POST /search/check`
  (admins) compares like the
  reconciliation (`IndexingService.compare`) but only counts: current, missing, outdated,
  vectors of another model, left over.
- **Rights.** The index query contains the rights (every document of the spaces the caller
  edits, in any lane; green documents of the spaces they read). Every hit is checked against
  the database once more and the filter applied again, so a removed member finds nothing of
  the space at once, before the index has changed; a page can therefore hold fewer items than
  `limit`. Documents still in processing are in the index, for the editors of their space.
- **Sections.** The text (at most `LEKTO_SEARCH_MAX_TEXT` characters) is cut into sections of
  about `LEKTO_SEARCH_CHUNK_SIZE` characters, at most `LEKTO_SEARCH_MAX_CHUNKS`; each gets a
  vector, and the first one starts with title, contact, type and the tags set (not their
  ancestors: nesting a tag elsewhere costs no embedding). `LEKTO_SEARCH_MAX_CHUNKS=1`
  gives one vector per document. A vector is made again only when model or section texts change.
- **Embeddings.** The query is embedded at request time (`LEKTO_SEARCH_EMBED_TIMEOUT`); if the
  endpoint is down or slow, the search falls back to words (`mode: words` with its `reason`).
  A query too slow goes on being embedded in the background (at most eight at once): the answer
  says `meaning_pending`, and once the vector is ready the searcher's event stream gets
  `search.meaning_ready` with the `query`; the web UI then offers to search again with meaning
  and keeps the words until asked (the list does not change under one's hands). The vector of a
  query is kept ten minutes in the API process, so paging and the search again do not embed it
  anew. Without embeddings the web UI shows nothing of this (`GET /pipeline`:
  `meaning_search`). `POST /documents/search/warm` (the web UI as soon as one types, at most once a minute)
  has the model loaded before the search needs it: Ollama unloads an unused model after a
  while, and loading Qwen3-Embedding 4B takes about seven seconds, one embedding then well under
  one.
  The model is Qwen3-Embedding 4B (`hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0` in Ollama, 2560
  dimensions) with an instruction before each query and none before the documents
  (`LEKTO_EMBEDDING_QUERY_PREFIX='Instruct: Given a search query, retrieve the German personal
  documents (letters, invoices, statements, contracts) that answer it\nQuery:'`, on one line);
  compared with `snowflake-arctic-embed2` (the model before), `bge-m3` and Qwen3-Embedding 0.6B
  and 8B in `evaluation/search/reports`.
  `LEKTO_EMBEDDING_DIMENSIONS` is the length of the vectors and required with Meilisearch and an
  embedding endpoint; vectors of another length are refused ("the vectors of <model> do not
  have the <n> dimensions configured"; the query then goes by words).
  Changing the model means a rebuild. Some models want a prefix for queries
  and documents (`LEKTO_EMBEDDING_QUERY_PREFIX`, `LEKTO_EMBEDDING_DOCUMENT_PREFIX`).
- **Limits.** Meilisearch ranks the documents nearest in meaning even if no word matches, so
  a hybrid search always returns hits; there is no threshold yet. A rebuild occupies one worker
  loop for its time. On a CPU the embedding of the sections dominates the indexing cost;
  `evaluate-search` measures it for a model.
- **Health.** `GET /health` includes `search` when it is configured. If only the search is
  down, the status is `degraded` and the answer stays `200`: the API works without it.

**Evaluation of the embedding model.** `lekto evaluate-search [--fake]
[--models a,b] [--ratios 0,0.5,1]` indexes the documents of the evaluation set with each model in
a temporary Meilisearch index and runs the queries of `evaluation/search/queries.json`; see
[evaluation/README.md](evaluation/README.md).

## Icons, colours and logos

- **Icons.** Tags of every scope and document types carry the name of a Lucide icon
  (`heart-pulse`: lower-case letters and digits in words joined by hyphens, at most 64
  characters; `appearance.checked_icon`). Only the form is checked: the web UI brings the icons
  in its own build and shows a stand-in for a name it does not know.
- **Colours.** A tag carries one of the twelve colours of the palette (`gray`, `red`, `orange`,
  `amber`, `lime`, `green`, `teal`, `sky`, `blue`, `violet`, `fuchsia`, `pink`; the web UI tunes
  each for light and dark) or an own one as `#rrggbb` (stored in lower case).
- **Logos.** A contact shows its logo, else its initials. The file is a WebP of at most 128 px
  at `contacts/<id>/logo.webp` (`objects.logo_key`); the contact keeps where it came from
  (`uploaded` or `fetched`), the domain of a fetched one and when it was stored
  (`Contact.logo`), and the domains whose fetch found none (`logo_failure`). It goes with its
  contact. File and contact change under one lock per contact (`logos.logo_lock`), the
  contact's row before the file: another change of the contact meanwhile fails the version
  check before the file is replaced, and the step starts again (three times).
  - *Upload* (admins): a PNG, JPEG or WebP image of at most 1 MiB, recognised by content; SVG is
    refused (`415`: it can carry scripts). The port `ImageNormaliser` (Pillow,
    `adapters/outbound/pillow`) reads PNG, JPEG, WebP and ICO only, checks the size before it
    decodes (at most 4096 × 4096 pixels; of an ICO every picture by its own header) and writes
    a WebP keeping transparency. An uploaded logo is never replaced by a fetched one.
  - *Fetch* (`LEKTO_LOGO_FETCH=true`; off by default, Lekto then never asks the web on its own):
    the worker's job `contacts.logo` asks the contact's own website for its icon, the port
    `LogoFetcher` (`adapters/outbound/logos`, httpx2). It is queued when a contact without a
    logo, or with a fetched one, gets a domain among its identifiers (entered by hand, learned
    by training, attached from a document; a logo found there replaces the fetched one, none
    found leaves it), by an admin (`POST /contacts/{id}/logo/fetch`; all its domains in turn,
    also one that failed; may replace a fetched logo) and for the contacts without a logo with
    `lekto fetch-logos`. A job that runs while `LEKTO_LOGO_FETCH` is off
    (switched off after it was queued) ends at once with the note "not fetched: fetching logos
    is off", without waiting or retries; the button answers `503` ("Lekto does not fetch
    logos") then. It reads the page of the domain (or of `www.`),
    the apple-touch-icon, `<link rel="icon">` with sizes and the web app manifest (with the
    standard library's `html.parser`), and `/favicon.ico`, and takes the largest raster icon of
    at least 64 px (at most four tried). The domains whose fetch finds none are noted and
    tried again only on request; a new domain is tried at once. No logo service of a third party is
    asked: it would learn whom one deals with.
  - *Protection against SSRF.* The domains come from documents. Every request and every
    redirect resolves the name and goes on only if every address it has is public (Python's
    `is_global`, and not shared 100.64.0.0/10, unique local, site-local, with a zone,
    IPv4-compatible, 6to4 or Teredo; a mapped or NAT64 IPv4 address counts as that address),
    then connects to the address it checked with the name as `Host` and for TLS (SNI and the
    certificate), so that a second answer of the name server cannot lead elsewhere (DNS
    rebinding). HTTPS on port 443 only, at most three redirects (each checked again), at most
    1 MB and 10 s per request (30 s per fetch), only the content types asked for, no encoding
    but gzip (decoded within the limit), no cookies, no proxies or `.netrc` from the
    environment (`trust_env=False`).

## REST API

`lekto api` (with `LEKTO_ROLE` `all` or `api`) serves
`adapters/inbound/rest` with Uvicorn on `LEKTO_API_HOST`:`LEKTO_API_PORT`. All routes are below
`/api/v1`; the OpenAPI document is `/api/v1/openapi.json`, the interactive docs `/api/v1/docs`.

Authentication: a session cookie from `POST /auth/login` or the OIDC callback, or a personal
API token as `Authorization: Bearer lekto_…` (a Bearer header wins over a cookie). Every route
depends on it except the five public ones (sign-in, OIDC start, info and callback, health); a
test calls every registered route without credentials and expects `401`. Requests that change
something need, with a session, the header `X-CSRF-Token` (from the sign-in answer or
`GET /auth/me`) and, with a token, the scope `read_write`; otherwise `403`. Changing sign-in
data needs a session, so a leaked API token cannot take over an account: the own password,
TOTP, tokens, sessions and links (`/auth/*`), and the admin endpoints that create users with a
password, reset passwords, turn TOTP off and remove links. Admins cannot reset their own
password or TOTP there; that goes through `/auth/*` with the current password or a code. Event streams check every 30
seconds that their session or token still holds and end otherwise.

The session cookie is `__Host-lekto_session`: HTTP-only, `Secure`, `SameSite=Lax`, `Path=/`, for
`LEKTO_SESSION_MAX_AGE`; with `LEKTO_COOKIE_SECURE=false` it is `lekto_session` without
`Secure`. Sign-in accepts JSON only, so a form on another site cannot sign anyone in.

| Endpoint | Purpose |
| --- | --- |
| `POST /auth/login` | Username, password, optional `code` or `recovery_code`; sets the cookie, returns the CSRF token |
| `POST /auth/logout`, `GET /auth/me` | Sign out; who is calling and how |
| `GET/PATCH /auth/me/profile` | The own profile: display name, aliases, birth date, e-mail, identifiers, the numbers at contacts (`numbers`, `declined_numbers`); what is given changes (a session; API tokens `403`) |
| `POST /auth/password` | Change the own password: other sessions end, `revoke_tokens` optional |
| `DELETE /auth/sessions` | End all other sessions |
| `POST /auth/totp`, `/totp/confirm`, `/totp/disable`, `/totp/recovery-codes` | TOTP |
| `GET/POST /auth/tokens`, `DELETE /auth/tokens/{id}` | Own API tokens |
| `GET /auth/oidc`, `/auth/oidc/login`, `/auth/oidc/callback`; `POST/DELETE /auth/oidc/link` | OpenID Connect |
| `GET /users`, `GET/PATCH/DELETE /users/{id}`, `GET /users/{id}/removal` | Accounts: list (others see active users' names, display names and personal spaces), role and state, delete with the spaces it settles (admins) |
| `GET/PATCH /users/{id}/profile` | A user's profile (admins and the user themself, with a session; an admin's API token reads and sets only the display name and e-mail, as a migration does) |
| `POST /users`, `POST /users/{id}/password`, `DELETE /users/{id}/totp`, `DELETE /users/{id}/oidc` | Create with password, reset password, turn TOTP off, remove links (admins, session only, not the own account) |
| `/contacts`, `/document-types`, `/tags`, `/fields` (`GET`, `POST`, `GET/PATCH/DELETE /{id}`) | Master data: read by all, changed by admins, deleted only when unused. Contacts and types take `group_ids`, contacts `topic_ids` (the topics they enable) and identifiers with an optional `topic_id`; a contact shows each caller the identifiers they see (see Profiles). Fields: name, description, choices and scope change, the data type does not; removing a used choice or narrowing the scope past documents with values is `409`. The lists take `document_counts=true` (and `all_users` for admins): each item with `document_count`, the documents in the caller's reach that have it (a field: a value for it; a tag: see Tags), counted in one query (tags in a few: the parents' counts and the groups' come apart) |
| `GET /tags` | The tags in the order of their trees (each after its parent, siblings by name; document tags, contact groups, type groups, topics), or of one `scope`; each with `scope`, `parent_id`, `path` (the names from the top), `assignment`, `shown`, `icon`, `color`. `POST` takes `scope` (default `document`), `parent_id`, `assignment` and `shown` (by scope unless given), `icon` and `color`; `PATCH` name, parent (`null`: the top), assignment, `shown`, `icon` and `color` (`null` removes them), never the scope. Document types take an `icon` too |
| `PUT/DELETE /contacts/{id}/logo`, `GET /contacts/{id}/logo` | A contact's logo (see Icons, colours and logos): upload (multipart `file`, admins; `413` above 1 MiB, `415` for another kind than PNG, JPEG or WebP, `422` if it cannot be read), remove (admins), read (everyone; WebP with `Cache-Control: private, max-age=86400`, the only answer of the API a browser may keep: `ContactOut.logo.url` carries the version). `ContactOut` has `logo` (source, domain, time, URL) and `logo_failure` (the domains whose fetch found none, the time of the last) |
| `POST /contacts/{id}/logo/fetch` | Fetch the logo from the contact's website (admins, `202`); `503` without `LEKTO_LOGO_FETCH`, `409` with an uploaded logo, `422` without a domain |
| `PUT /document-types/{id}/fields` | The fields of a document type, each required or optional, set from the type in one transaction (admins); answers its fields. A new type takes them with `POST /document-types` (`fields`), in the same transaction as the type, so its title pattern may name them. A global field is `422`; taking off a field that has values on its documents or that the type's title pattern uses is `409` |
| `POST /contacts/{id}/identifiers` | Attach one identifier to a contact, entered by hand (admins), optionally with a `topic_id` the contact enables and, for a customer or personnel number, the `user_id` it belongs to; the others stay; `409` if another contact has it by hand or it is a person's. `PATCH` replaces the whole list; a person's kinds are `422` |
| `GET/POST /spaces`, `GET/PATCH/DELETE /spaces/{id}`, `PUT/DELETE /spaces/{id}/members/{user_id}` | Spaces the caller is a member of (admins: all), with `personal_of`, the caller's `role`, the `members` and the `description` (what belongs in it, for the language model, at most 300 characters); create (`members`, `description`; the caller edits it, an admin may give the members alone), rename and describe (`PATCH` with `name` and/or `description`, null removes it; a personal space keeps its name), delete (empty, never a personal space), members with `role` `read` or `edit` and their `username` and `active` (editors; of a personal space its user); every member leaves a space themselves (`204`) |
| `GET /documents/search` | Search: `q`, the filters of `GET /documents`, `sort` (`relevance`, the default, or a key of `GET /documents`; relevance breaks ties), `limit`, `offset`, `semantic_ratio`; hits with snippet (the document with `in_inbox`, as in `GET /documents`), `estimated_total`, `next_offset`, `mode` with `reason` and `meaning_pending` (and `semantic`) |
| `POST /documents/search/warm` | Have the model of the embeddings loaded before a search needs it (`204`, one embedding in the background, at most once a minute) |
| `POST /search/reindex` | Rebuild the search index in the background (admins); `202` |
| `GET /documents` | Readable documents, each with `in_inbox` (it stands open in the caller's inbox); `sort`: `-created_at` (the default, newest first), `created_at`, `document_date`, `-document_date`, `title`, `-title` (without case and accents), `field`, `-field` (the value of the field `sort_field_id`: a date, a period by its first day, a number, an amount by its value; `422` for other types), documents without a date or value last either way; filters `contact_id`, `document_type_id`, `space_id` (each repeats, one of them must match), `tag_id` (with the tags below it; repeats, all must match), `contact_group_id` and `document_type_group_id` (the document's contact or type in the group or one below it; each repeats, one of them must match), `topic_id` (the topic or one below it; repeats, one of them must match), `document_date_from` and `document_date_to` (the document date lies between them, both days included, either end open; a document without a date does not match; `422` if the end lies before the start), `lane`, `field_id` (a value for the field), `fact` (a fact the document has, none a person rejected, as `kind:value:role`, the value as written, needing its kind and possibly holding colons, any part empty for any: `invoice_number:4711:`, `contract_number::`, `::refers`; repeats, all must match; at most five; a person's facts, by a kind that is a person's alone or by the role `person`, only for admins, `403`, also in a lens), `all_users` (admins); `limit`, `cursor` (`next_cursor` of the page before, an opaque value naming its last document; its sort value is looked up, `422` if that document is gone) |
| `GET /documents/facets` | Counts for the filters of the document view, with the filters of `GET /documents` and `all_users` (admins): `total`, per contact and type (`id` null: without one), group of contacts and of types, topic and tag (each with the documents of those below it, once), year and its months of the document date (`undated`: without one). Contacts, types, groups, topics and the period combine as either-or and count without their own choice, so each tells what one more would add; tags count with the whole filter |
| `POST /documents` | Upload (multipart: `file`, optional `space_id` (a space the caller edits; default: the uploader's personal space), optional `channel=migration`, `uploaded_by` and `metadata` for admins; otherwise the channel is `web` with a session, `api` with a token); `202` with `id`, `status_url` |
| `GET/PATCH/DELETE /documents/{id}` | Metadata and state with the caller's access, `channel`, `topic_id` (see Topics); change (editors; the answer has the change rules' `rules` report); delete (editors and admins); `uploaded_by` names who uploaded it, `access` is `read` or `edit` |
| `POST /documents/{id}/dry-run` | A change as with `PATCH`, with the change rules, nothing stored: the result, the differences and who would see it (`visibility`: the space and its `members`) |
| `POST /documents/{id}/move` | Into a space the caller edits, or into another user's personal space (hand over; `personal_space_id` in `GET /users`); editors of the document's space, admins anywhere |
| `GET /documents/{id}/original`, `/archive`, `/preview`, `/pages/{number}` | Files (read access); pages from 1 to `page_count` |
| `GET /documents/{id}/text` | The text as it is set (plain text, pages apart by form feeds) in pieces: `offset`, `limit` (at most `LEKTO_MCP_TEXT_MAX`, the default); `409` while not parsed |
| `GET /documents/{id}/files` | The files as stored (read access): when the document was added and changed, its original's name and type, and for the original and the archive (null while there is none) size, SHA-256 and metadata: a PDF's version, PDF/A level, pages, document information and XMP; an image's format, size, resolution and EXIF |
| `GET /documents/{id}/facts` | What the document shows of its contacts (read access): names and identifiers with the contact they belong to now and their spans in the text (characters, as `/text` counts them), each with where it stands on the archive's pages (a box per line; none for a text parsed before 0.2); the codes on its pages, each once for its format and text, with the pages and boxes where it stands (a box per copy), the GiroCode read, their identifiers and the amount fields of the same value; for admins, on the documents of how many other contacts an identifier stands; for the editors of its space and admins the persons it names (`persons`: name, strength, kinds of evidence, spans; `null` for readers; what is private about a person finds them only for admins and that person, anyone else sees another user by their display name alone); `409` while not parsed |
| `GET /documents/{id}/log` | Processing log (editors and admins) |
| `POST /documents/{id}/retry` | Repeat the failed nodes (editors and admins) |
| `POST /documents/{id}/reprocess` | `{"from_node": "ocr"}`: process again from a node, with every node after it (editors and admins) |
| `POST /documents/{id}/vision` | Process again from OCR with the vision language model reading every page (editors and admins); `409` without a model |
| `GET /documents/{id}/reading` | How the archive's text was read: by the vision model or not, each recognised page, the advice to read with the model (editors and admins) |
| `GET /pipeline` | The graph: every node and what it needs, in graph order; the vision model, if one is configured; whether logos are fetched (`logo_fetch`); whether the search takes the meaning into account (`meaning_search`) |
| `POST /pipeline/reparse` | Read the text of every document again in the background (admins, after the update to 0.2); `202` with `queued` |
| `GET /inbox` | The caller's inbox (see Inbox), newest first, with open nodes and fields: everything open, or one `tab` (`new`, `review`, `intervene`, `processing`, `done` with how, when and by whom, newest first by when it left); `limit`, `cursor`, `all_users` (admins) |
| `GET /inbox/summary` | The count of each tab, `open` (all but done) and the worst lane among the open documents; `all_users` (admins) |
| `PUT/DELETE /documents/{id}/seen`, `POST /inbox/seen` | Seen per user: the caller saw a document (read access; the web UI, when its view opens), it is new again (read access), everything new in the inbox as seen (`marked`; `all_users` for admins) |
| `GET /documents/{id}/review` | What the model proposed and how each field was checked (editors and admins) |
| `POST /documents/{id}/confirm` | Decide the open fields (`changes` as with `PATCH`, `accept_suggestions`, `space_id`; an open space with a suggestion moves there with `accept_suggestions` and stays otherwise, both a decision of its space), then continue from `resume_at` (`apply_rules`, or `fields` after a type change) up to filing (editors and admins); undecided fields: `422` with `open_fields`; handed over or out of the caller's reach: `{id, access: null}` |
| `GET/POST /rules`, `GET/PUT/PATCH/DELETE /rules/{id}`, `GET /rules/{id}/versions`, `/versions/{number}` | Rules: list (`scope`, `space_id`, `include_disabled`, `all_users` for admins), create (`scope`, `space_id`, `enabled: false` to save it switched off), change (new version; with `scope`, `space_id` it moves; `enabled` switches it with the change), enable or disable, delete; see Rules |
| `POST /rules/{id}/apply/preview`, `POST /rules/{id}/apply`, `GET /rule-applications/{id}` | Apply a rule to existing documents: preview, start (`202`), progress |
| `GET /events` | Server-sent events of the documents the caller may read, for admins also `classifier.trained`; `?document_id=` |
| `GET/POST /webhooks`, `GET/PATCH/DELETE /webhooks/{id}` | Webhooks: the caller's own (admins read everybody's, `?owner=`); create (the answer shows the secret once), change, switch on or off, delete; see Webhooks |
| `POST/DELETE /webhooks/{id}/secret`, `POST /webhooks/{id}/test`, `GET /webhooks/{id}/deliveries` | Renew the secret (the old one signs 24 hours longer; an unsigned webhook signs from then on) or stop signing, send a test request, the delivery log (`before`, `limit`) |
| `GET/POST /lenses`, `GET/PATCH/DELETE /lenses/{id}`, `PUT /lenses/order` | Lenses, the caller's saved looks at the documents (only theirs; others' are `404`, also for admins): `filter` (the filters of `GET /documents` as lists, `document_period` `this_year`, `last_12_months` or `last_year` moves with the day, `facts` as `kind`, `value`, `role`, the value kept normalised), `query`, `sort` (`relevance` only with `query`, `field` only without), `sort_field_id`, `grouping` (`none`, `month`, `due`, `document_type`, `contact`), `layout` (`grid`, `list`), `card_field_ids` (at most three), `due_field_id` (a date field); names unique per user, at most 100; deleted master data and fields are left out when a lens is read; `order` takes each lens once |
| `GET /health` | Database, bucket or storage directory and, if configured, the search index reachable; `200` (`ok`, or `degraded` if only the search is down) or `503`, no authentication; not written to the access log |

- Uploads are streamed into a temporary file and hashed on the way; the limit
  `LEKTO_UPLOAD_MAX_SIZE` applies while receiving (`413`). The type is recognised from the
  content (PDF, JPEG, PNG, TIFF; otherwise `415`). Every file exists once per installation: a
  file that lies in Lekto already is `409`, with `existing_document_id` if the caller may read
  that document; without it, the file lies in a space the caller cannot see. Moving,
  confirming and rules never meet a duplicate.
- Reasons come with codes (issue #83, `core/domain/reasons.py`): beside the English text
  (`reason`), a check (`FieldCheckOut`), a rule's note (`RuleNoteOut`), a log entry
  (`LogEntry`, stored in `processing_log.reasons` since revision 0038) and an open node of the
  inbox carry `reasons`, each a `code` with its `params`, the custom field it is about
  (`subject`), the rule it comes from (`rule`) and, among a node's reasons, the built-in field
  (`field`). A signal that abstains writes `abstained_reason` beside `abstained` in its output,
  the rules `problem_reason` beside `problem` (also `ArrivalStepOut`); a document the adapters
  cannot process fails its node with the error's own code (`DomainError.reason`). A migration
  gives the default reasons of its reviews with their codes (`ImportedReviewIn.code`, one of
  `paperless_*_review` with `name`); a reason a person wrote has none. The OpenAPI document lists every code with its parameters and how each is
  written (`x-reasons`: `text`, `number`, `percent` (0 to 1), `date`, `value` (a field's value
  as a reason shows it: true or false for yes or no, null for none), `names`, `fields` (check
  fields), `rule_values`). `text` is a reason as written (a person's, or one stored before
  codes); the log keeps the English text beside the codes, and an entry from before has the
  text only. Clients translate the codes they know and show the text for the others.
- Errors are problem details (RFC 9457, `application/problem+json`) and documented per endpoint.
  An error with a code of its own carries it as `reason` beside `detail` (a domain error raised
  with a `Reason`; one raised with a text has none). A request that does not fit (422) lists
  each part in `errors` (`field`: its path joined by `.`; `message` in English; `reason` with
  an `input_*` code from Pydantic's error type, `input_invalid` with the message for the rest);
  `detail` joins them as `field: message; ...` as before. Codes also for what is not found
  (`not_found` with the kind of thing), names that are empty or too long, and what only some
  may do (`admins_only`, `editors_only`, `admins_cannot` with an `action`); a rule disabled
  automatically keeps why with its code (`RuleOut.disabled_reasons`, `rules.disabled_reasons`
  since revision 0039), a rule application each skipped document's reason
  (`SkippedOut.reasons`). The value checks a person meets in the UI have codes too
  (identifiers with the `value` refused, profiles, contacts, tags, fields, spaces, passwords,
  webhook URLs, icons and colours, lenses, rule patterns). Still as text: the checks only a
  faulty client trips (choices, the rule structure, lens filters), the messages of the template
  engine, and the upload's size and type (the UI words them itself).
  Filing into a space without edit rights (upload, move, confirm, a rule that sets the space)
  is `403` with `space_id`, the space that was refused.
- Documents and spaces the caller may not see are `404` with the same answer as missing ones;
  lists, filters and pages only ever contain readable documents (the repository query follows
  the permission rule, and the service checks every result again). Yellow, red and unfinished
  documents are their space's editors' only.
- Every answer below `/auth` carries `Cache-Control: no-store` (CSRF tokens, TOTP secrets,
  recovery codes, API tokens), also errors and redirects. The OpenAPI document, the docs and
  `/health` stay public. Every other answer of the API is `no-store` too, but for a contact's
  logo (`GET /contacts/{id}/logo`, successful answers only), which keeps its own
  `private, max-age=86400`: its URL changes with the logo, so lists need not load it again.
- Request bodies other than uploads (documents, logos) are bounded by `LEKTO_REQUEST_MAX_SIZE`, by
  `Content-Length` before anything is read and by the bytes received otherwise (`413`);
  FastAPI would otherwise read a JSON body of any size into memory.
- Downloads go through a temporary file and carry `Content-Security-Policy: sandbox`, besides
  the `Cache-Control: no-store` and `X-Content-Type-Options: nosniff` of every answer.
- `401` (with `WWW-Authenticate: Bearer`), `429` (with `Retry-After`) and `502` (identity
  provider) are problems like all errors. The access log shows the OIDC callback without its
  query (code and state).
- Event streams: the API subscribes to the event bus as `api.sse` and polls the outbox every
  `LEKTO_EVENTS_POLL_INTERVAL`. Each event goes to the streams of the users who may read the
  document at that moment (other users once it is green). No replay: after reconnecting,
  clients fetch the state. `document.deleted` goes to the streams of the users who could read the
  document when it was deleted (the event carries their ids; the stream message does not).
  `classifier.trained` (a new model: `number`, `examples`) goes to the active admins' streams
  that do not follow one document; webhooks cannot choose it. One API instance
  is assumed: several would share the `api.sse` subscription. While the API is down, its
  subscription holds back the purge of the outbox.
- On SIGTERM the event streams end at once, open requests get ten seconds, then the database
  engine and the S3 client are closed.

## Worker

`lekto worker` (with `LEKTO_ROLE` `all` or `worker`) runs
`adapters/inbound/worker`:

- `LEKTO_WORKER_CONCURRENCY` loops claim and run due jobs; each waits
  `LEKTO_WORKER_POLL_INTERVAL` when nothing is due. One loop delivers outbox events
  (`EventBus.dispatch`) every `LEKTO_EVENTS_POLL_INTERVAL`. Postgres `LISTEN/NOTIFY` is not
  used.
- Memory: OCRmyPDF takes about 150 MB per job, the worker itself about 0.5 GB; reading the
  text needs little. The OCR is bound by the CPU: OCRmyPDF shares the cores among
  `LEKTO_WORKER_CONCURRENCY` jobs, so more loops than cores gain nothing.
- The cleanup (`maintenance.cleanup`, one job with a fixed dedup key; it goes before pipeline
  steps when due) runs every
  `LEKTO_CLEANUP_INTERVAL` and removes finished jobs and delivered events older than
  `LEKTO_RETENTION`, webhook delivery log rows of that age, ended sessions, stale counts of
  failed sign-ins, the previous secrets of webhooks whose grace period
  (`LEKTO_WEBHOOK_SECRET_GRACE`) is over, and what only the inbox's done needs after 14 days
  (see Inbox). The same loop runs the removal of a deleted document's files.
- Pipeline steps go before index jobs: the search index lags behind a bulk ingest and catches
  up when no step is due (the document lists read the database, not the index).
- Rule applications (`rules.apply`) run 25 documents per job, then queue the next job, so
  pipeline nodes do not wait behind them.
- After a tag moved, `tags.normalise` leaves what carries it and a tag now above it the one
  below (after rule applications; see Tags); a row changed meanwhile fails the version check,
  and the job runs again (five tries, waiting from a minute, doubling).
- With `LEKTO_LOGO_FETCH`, the job `contacts.logo` fetches the logo of a contact (after rule
  applications, before training; see Icons, colours and logos). It asks the network outside
  any transaction and is repeated only for other errors than the website's (three tries).
  Without it, a job queued before ends at once (failed, with the note that fetching is off).
- `LEKTO_WEBHOOK_CONCURRENCY` further loops deliver webhooks (see Webhooks); a receiver that
  does not answer holds up deliveries, never the pipeline.
- SIGTERM or SIGINT: no new jobs; running jobs may finish within
  `LEKTO_WORKER_SHUTDOWN_TIMEOUT`, then they are cancelled and their jobs released to run again
  at once. Finally the database engine and the S3 client are closed.
- Failed event deliveries are repeated with doubling delay from one second up to an hour, at
  most `LEKTO_EVENTS_MAX_ATTEMPTS` times. Several dispatchers under the same subscriber name
  may deliver an event twice (at least once is allowed).
- Every loop runs its units of work one after another, never nested, as SQLite requires.
- A job keeps when its latest claim took it, when it was done or given up, and what a done job
  reports (`jobs.started_at`, `finished_at`, `result`; revision 0041). `/jobs` shows them on the
  page "System" to every user (`JobsService`): counts by kind and state (`GET /jobs/summary`,
  one `GROUP BY`), the jobs (`GET /jobs`; a document named only to those who may read it, the
  last error only to admins), how long the done ones waited and ran within `LEKTO_RETENTION`
  (`GET /jobs/durations`: median and 90th percentile by nearest rank, from the latest 2000 done
  jobs of each kind, counted at most once a minute per API process), and an admin queues a
  failed one again (`POST /jobs/{id}/retry`; a failed processing step goes through
  `POST /documents/{id}/retry`, so that its document's processing goes on).

## Webhooks

A user subscribes to document events and Lekto sends a `POST` to a URL (n8n, Home Assistant,
Node-RED, any service), signed unless the webhook goes without a secret. Webhooks belong to the
user who created them; the API is under `/webhooks` (create, list, change, switch off, delete,
renew or remove the secret, test, delivery log). Admins may do everything with every webhook:
read it and its log, change, delete, test, renew the secret (which then shows to them, once).
Nobody sees a secret again after it was shown, nor the value of a header the webhook sets. What
an admin reads includes the target URL (which may be a capability URL), the names of its headers
and, in the log, the document IDs and event types of that user's deliveries.
At most `LEKTO_WEBHOOKS_PER_USER` (20) per user.

**Events.** `document.received`, `document.node_started`, `document.node_deferred`,
`document.node_delegated` (a node waits for the answers to its tasks, `deadline`),
`document.node_completed`, `document.lane_changed`,
`document.filed`, `document.updated`, `document.deleted`, or `*` for all, also future ones;
none for a webhook that only rules use. Three more say in a receiver's words what the others
tell: `document.review_required` (it waits in the inbox, yellow or red; `lane`),
`document.confirmed` (a person confirmed it in the inbox) and `document.moved` (it lies in
another space, `space_id`; `by_person`, and `handed_over` when that is the personal space of
another user than the one who moved it, or, moved by processing or a rule, uploaded it); the
web UI does not listen to them. A webhook only hears of documents its owner may read, as with
the event stream: the right is
checked when the event is queued and again before every attempt, and a user who lost access in
between gets nothing (the log shows `dropped`). The body carries no lane, so a receiver
that wants the state of the document fetches it; `document.filed` is not sent while the document
is still being processed. `document.deleted` goes to those who could read the document
when it was deleted.

**Rules that send** (`send_webhook`, Tobi, 25.10.2026). A rule sends a request through a webhook
of whoever saves it (someone else's is not found, `404`); the type is `rule.send`, the body
names the rule (`rule`: `id`, `name`) and follows the webhook's body format. On arrival the
request goes once the document is filed: a green one at once, a yellow one after a person
confirmed it, a red one never, and none twice although the rules run again after the
confirmation. After a change, a move or applying a rule to existing documents (one request per
document; the preview lists them) it goes once that is stored. It is queued in the transaction
that stores what the rules did. The webhook's owner must be able to read the document where it
ends up: on arrival the document turns yellow otherwise (`rule_webhook_unreadable`), unless a
person decided in this run already (then, and outside processing, it is only reported in the
log, `sends_refused`). Deleting a webhook disables the rules that send through it, with the
reason; so does deleting its owner.

**Tasks** (requests that expect an answer, Tobi, 25.10.2026, `.idea/webhooks-und-auftraege.md`).
A node that needs an answer from outside hands the request to a task and waits for it without
a worker: its state is `delegated` (the web UI says "running externally", with the minutes
left), and `deadline` says when the last of its tasks ends at the latest. Whenever one of its
tasks ends, the node runs anew and reads what its tasks brought. A webhook takes at most
`max_open_tasks` tasks at the same time (4; 1 to 64); more wait in Lekto, and their time to
answer starts when they are sent. A task's request goes like any other (body format, headers,
signature) and carries four headers more: `lekto-task-id`, `lekto-callback` (where to answer),
`lekto-task-token` (a one-time token; Lekto keeps only its hash once the request was delivered)
and `lekto-deadline`; `thin` and `full` bodies hold them as `task` (`id`, `callback`, `token`,
`deadline`), a template sees `task.*`. The request is repeated until the deadline while the
receiver is unreachable; one that is refused, or a template that does not make JSON, ends the
task at once. A webhook that takes tasks is never switched off.

The consumer answers with `POST /api/v1/external/tasks/{id}/result`, the token as
`Authorization: Bearer` (never in the URL), and an envelope: `{"status": "ok", "answer": ...,
"producer": "..."}` (any JSON; `producer` is optional and goes into the log) or `{"status":
"error", "reason": "..."}`. `204`: taken. An `error`, an envelope that is not valid (`422`, the
answer says why) and one larger than 1 MB (`413`) count as no answer, and use the token up.
`409`: the task was answered before, or its document was processed again or deleted. `401`:
unknown task or token, or the deadline has passed. Without `LEKTO_PUBLIC_URL` no task can be
sent (the consumer would not know where to answer). Deleting a webhook fails the tasks that
wait for it; those it sent run to their deadline, and an answer is still taken.

**Model calls** (Tobi, 25.10.2026, `.idea/webhooks-und-auftraege.md`). An admin may make one of
their webhooks serve as a model call (`model_call`: `kind` `propose` or `extract`,
`timeout_seconds`, default 300, 30 to 86,400): it then answers that request instead of the
language model of `LEKTO_LLM_*`, for every document (an exception to "webhooks see what their
owner may read"). Of the active webhooks of active admins at most one serves each kind (`409`
`model_call_taken`); a webhook switched off, deleted, or whose owner is no admin any more serves
no more, and the language model answers again (without one `signal_llm` abstains).
`propose` takes over `signal_llm` (prompt `propose-6`), `extract` the request of `fields` for
the fields the proposal did not give (another type decided, or no proposal; prompt
`extract-6`). The context does not follow the prompt's form: the contracts stay
`propose-ext-1` and `extract-ext-1`. The node sends a task
whose body is always the context, whatever the webhook's `body`: `contract` (`propose-ext-1`,
`extract-ext-1`), `task` (`id`, `kind`, `document_id`, `run`, `deadline`, `callback`, `token`),
`document` (`filename`, `media_type`, `pages`, `received`, the text in full, and signed links to
`content.json` and the page images), the master data the prompt lists (contacts, the 20 the text
names most, document types, fields by key, tags, spaces by key) and `answer_schema`, the answer's
JSON Schema with the rules of the system prompt as descriptions. The contract is in the OpenAPI
document under `webhooks` (`external.propose`, `external.extract`; also the events, `rule.send`
and `rule.ask`). The answer's structure is checked when it comes (`422` and the document is red
if it does not fit); its values are checked as the model's (quotes literally in the text, the
reading confidence, a contact green only with a second signal or hard evidence). An `error`,
an answer that does not fit and none by the deadline make the document red; there is no second
attempt. The context (without the task and its links) and the answer lie beside the document as
the model's exchanges do; the log names the contract and `producer`. Documents taken over from
Paperless-ngx send no task. `signal_llm` waits for the page images (`pages`), so the links
work when the task goes; it does not need them, so processing again from `pages` leaves it
alone (`GET /pipeline`: `waits_for`).

`GET /api/v1/external/tasks/{id}/files/{name}?expires=…&signature=…` gives a model call's files
(`content.json`, `pages/<n>.webp`): each link is signed with `LEKTO_SECRET_KEY`, bound to the
task, its document, its run and the file, and holds until the task's deadline (`401` otherwise)
while the run is the document's current one (`409` once it was processed again or deleted). An
example consumer (Python, standard library, Ollama) is in `examples/model-calls/`.

**The request.** `POST <url>`, `Content-Type: application/json`, `User-Agent: Lekto/<version>`,
the webhook's own headers, and a body as the webhook chooses (`body`):

- `thin` (the default) names the event only; the receiver fetches details through the API with
  a token of its own:

  ```json
  {"id": "01999d5e-...", "type": "document.filed", "occurred_at": "2026-10-08T12:00:00Z",
   "document_id": "01999d5e-..."}
  ```

- `full` adds `document`, as it is when the request goes (`null` once it is deleted): `id`,
  `title`, `original_filename`, `contact`, `document_type`, `topic` and `space` (each `{id,
  name}` or `null`), `tags` (`[{id, name}]`), `document_date`, `added`, `lane`, `channel`,
  `pages`, `fields` (the fields with a value, by key, in the API's form: an amount as `{amount,
  currency}`) and `link` (`LEKTO_PUBLIC_URL/ui/documents/<id>`; `null` without
  `LEKTO_PUBLIC_URL`).
- `template` sends what `body_template` makes: Liquid that has to give JSON (up to 10,000
  characters). It sees what a rule's template sees (`title`, `contact`, `document_date`,
  `field.<key>`, ...), and `event` (`type`, `id`, `occurred_at`), `document_id`, `lane` and
  `link`. The filter `json` writes a value as JSON in the API's form, `| default: nil` a missing
  one as `null`; writing a missing value without it fails. A Home Assistant notification:

  ```liquid
  {"title": {{ document_type | default: "Dokument" | json }},
   "message": {{ title | json }}, "amount": {{ field.betrag.amount | default: nil | json }},
   "url": {{ link | json }}}
  ```

  The template is checked when saved (syntax, known values) and is previewed with a document
  like a rule's (`POST /templates/preview` with `purpose: webhook`). A request whose template
  does not give JSON, or writes a missing value, is not sent: the log shows `gave_up` with the
  reason, without repetition.

`id` is the event id: it is the same in every repeated attempt, so a receiver can recognise
events it has handled. Delivery is at least once and not in order; sort by `occurred_at`. The
test request (`POST /webhooks/{id}/test`) has `type: "webhook.test"` and `document_id: null`;
it goes out at once, to whatever address the webhook names, so a user may send at most ten per
minute (`429` with `Retry-After` beyond that; counted per API process).

**Headers of its own.** A webhook may set up to 20 headers that go with every request, e.g.
`Authorization: Bearer <token>` for a receiver that checks a token instead of a signature (Home
Assistant and Node-RED do not verify signatures by themselves). Names are HTTP tokens; Lekto sets
`content-type`, `content-length`, `host`, `connection`, `transfer-encoding` and every header
beginning with `webhook-` or `lekto-` itself, so those are refused. Values are printable ASCII
(up to 4096 characters, spaces only inside), stored encrypted with `LEKTO_SECRET_KEY` and never
shown again; the API shows the names. Changing the headers (`PATCH`, `headers`) gives all of
them in order; a header given without a value keeps the one it has. A `User-Agent` of its own
replaces Lekto's.

**Signature** ([Standard Webhooks](https://www.standardwebhooks.com), so ready-made verification
libraries work). A webhook created with `"signed": false`, or whose secret was removed (`DELETE
/webhooks/{id}/secret`), sends `webhook-id` and `webhook-timestamp` but no signature; renewing
the secret makes it sign again. A signed request has three headers: `webhook-id` (the event id),
`webhook-timestamp` (Unix seconds of this attempt) and `webhook-signature`, `v1,<base64>` of the
HMAC-SHA256 over
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
`LEKTO_WEBHOOK_TIMEOUT`, certificate refused), `5xx`, `408`, `425` and `429` are repeated, up to
`LEKTO_WEBHOOK_MAX_ATTEMPTS` attempts with `LEKTO_WEBHOOK_RETRY_DELAY` doubling up to an hour
(30 s, 1, 2, 4, 8, 16, 32, 60, 60 minutes: about three hours). `3xx` and every other `4xx` are
final: redirects are never followed, since the signature would not hold for another target.
After `LEKTO_WEBHOOK_DISABLE_AFTER` (20) deliveries given up in a row Lekto switches the webhook
off (`active: false`, `disabled_reason: failing`); switching it on again clears the count.
A receiver that is down delays the deliveries behind it, since the `LEKTO_WEBHOOK_CONCURRENCY`
loops wait for it up to the timeout per attempt; the pipeline is not affected.

**The log** (`GET /webhooks/{id}/deliveries`, newest first) has one row per attempt: time,
event, `outcome` (`delivered`, `retrying`, `gave_up`, `dropped`), HTTP status, duration, error
and the time of the next attempt. The receiver's answer is neither stored nor shown. Rows are
removed after `LEKTO_RETENTION`.

**Secrets.** Lekto generates the secret and shows it once, in the answer to creating a webhook
or renewing its secret. It is stored encrypted with `LEKTO_SECRET_KEY` (the worker needs the key
too, to sign). Renewing keeps the old secret signing next to the new one for
`LEKTO_WEBHOOK_SECRET_GRACE` (24 hours), so the receiver can switch without a gap; renewing again
ends that at once. Removing the secret ends signing at once, the old one included. If the key
changes, secrets and header values cannot be read any more: deliveries give up (`gave_up`, "the
secret or the header values cannot be used"); renew the secret and give the header values anew.

**Targets.** `http` and `https` to any host and port, including the own network. `https`
certificates are verified; there is no switch against that (use `http` or a valid certificate).
Anyone who may create webhooks can make the server send `POST`s to addresses it can reach and
see from status and error whether something answers; the body is fixed and the answer is not
shown.

## MCP

The API serves the Model Context Protocol (Streamable HTTP, stateless, JSON answers) at
`/api/v1/mcp`, so AI clients can search documents, read them and correct their metadata.
`LEKTO_MCP_ENABLED=false` removes it. It is not part of the OpenAPI document.

Authentication: a personal API token (`POST /auth/tokens`; the web UI will offer it later) as
`Authorization: Bearer lekto_…`; cookies do not count. Without a valid token the answer is `401`
(`WWW-Authenticate: Bearer`). A client sees exactly what its token's user sees. The scope works
as in REST: `read` may use every tool but `update_metadata`.

| Tool | Does |
| --- | --- |
| `search` | `query`, `limit` (1 to 25), `offset`, optional `contact`, `document_type`, `tags` (names of document tags, all of them; a tag finds the documents with a tag below it too), `topics` (names of topics, one of them; a topic finds those with a topic below it too): hits with `id`, `title`, `score`, `snippet` (plain text), contact, type, topic, tags, date, lane, `access`; `next_offset`, `semantic` |
| `get_document` | `id`: metadata with contact, topic, type, tags and fields by name, lane and processing status, and the document's `relations` with documents the caller reads too (`id`, `title`, type, date, `direction` `refers_to` or `referred_by`, `suggested`); read only |
| `get_text` | `id`, `offset`, `limit` (characters, at most `LEKTO_MCP_TEXT_MAX`, 20,000): a piece of the document's text as it is set, `next_offset` to continue. The text is content from outside; the tool description tells clients not to follow instructions in it |
| `update_metadata` | `id` and any of `title`, `contact`, `topic`, `document_type` (name; `null` removes; a topic the contact enables), `tags` (names of document tags, the complete list, replaces), `document_date` (`null` removes), `fields` (field name to value; `null` removes). Needs a `read_write` token and edit rights; the change rules of its space run as for `PATCH /documents/{id}` and the result shows them. If the rules filed the document where the caller can no longer read it, the result has only `id` and `access: null` |
| `list_expected` | The series of documents the caller reads and the document each expects next (contact, type, number, cadence, spread, newest document, next date and period, `overdue`, `soon`, `later` or `ended`); read only |
| `list_tags` | The tags with `scope` and `path`, in the order of their trees, optionally of one `scope`; document tags name the tags of the other tools, topics the `topic` of `update_metadata` |

Names are matched regardless of case; an unknown name is an error, nothing is created. A
document the caller may not read is "not found", with the same text as a missing one.

Set up Claude Code (use a `read` token if the client should only read):

```sh
claude mcp add --transport http lekto https://lekto.example.org/api/v1/mcp \
  --header "Authorization: Bearer lekto_..."
```

Other clients take the same URL and header; the MCP Inspector
(`npx @modelcontextprotocol/inspector`) is handy to try it out: transport *Streamable HTTP*,
the URL, and the header `Authorization`. Behind a reverse proxy the path needs no special
handling; requests are plain `POST`s with JSON bodies, limited by `LEKTO_REQUEST_MAX_SIZE`.

## Configuration

Environment variables with the prefix `LEKTO_` only; there is no configuration file. The command
line alone takes them from a file, too: `lekto --env-file FILE`, for the development instance in
the devcontainer (`.devcontainer/dev.local.env`), whose environment holds the test settings; the
file's `LEKTO_` variables then replace all others. Invalid or
contradictory configuration stops the start with a message naming the variables. Check it with
`lekto` (`lekto check`), which prints the effective configuration without secrets.

Secrets (marked *secret*) can also be passed as `LEKTO_<NAME>_FILE=/run/secrets/...` (Docker
secrets): the file content, without one trailing newline, is the value. Setting both
`LEKTO_<NAME>` and `LEKTO_<NAME>_FILE` is an error. In production, pass at least
`LEKTO_SECRET_KEY_FILE` and `LEKTO_ADMIN_PASSWORD_FILE` that way. The key and the admin
password in `.devcontainer/compose.yml` are public; with secure cookies the start refuses the
development key.

Variables for the variant that is not selected (for example `LEKTO_DB_HOST` with
`LEKTO_DB_TYPE=sqlite`) are not required, but must still be well-formed if set.
Choices are case-insensitive; surrounding whitespace is removed and blank values count as unset.
Durations must be positive.

The table names every variable (a test checks it against `settings.py`). **Role** says which
service reads it: `API`, `Worker` or `both`; a container with `LEKTO_ROLE=all` needs them all,
separate API and worker containers only theirs (the connection and storage settings in both).
Durations are seconds (`30`, `1.5`) or ISO 8601 (`PT1H`, `P7D`).

| Variable | Role | Default | Meaning |
| --- | --- | --- | --- |
| `LEKTO_ROLE` | both | `all` | `all`, `api` or `worker`: which services run (the image's s6 scripts read it) |
| `LEKTO_LOG_FORMAT` | both | `json` | `json` or `console` |
| `LEKTO_LOG_LEVEL` | both | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LEKTO_DB_TYPE` | both | `sqlite` | `sqlite` or `postgres` |
| `LEKTO_DB_SQLITE_PATH` | both | `data/lekto.db`; image: `/data/lekto.db` | SQLite only; local volume (WAL), never a network share |
| `LEKTO_DB_HOST` | both | unset | required for `postgres` |
| `LEKTO_DB_PORT` | both | `5432` |  |
| `LEKTO_DB_NAME` | both | unset | required for `postgres` |
| `LEKTO_DB_USER` | both | unset | required for `postgres` |
| `LEKTO_DB_PASSWORD` | both | unset | *secret*; required for `postgres` |
| `LEKTO_STORAGE_TYPE` | both | `filesystem` | `filesystem` or `s3` |
| `LEKTO_STORAGE_PATH` | both | `data/objects`; image: `/data/objects` | filesystem only |
| `LEKTO_S3_ENDPOINT_URL` | both | unset | required for `s3`, e.g. `http://garage:3900` |
| `LEKTO_S3_REGION` | both | `us-east-1` |  |
| `LEKTO_S3_BUCKET` | both | unset | required for `s3` |
| `LEKTO_S3_ACCESS_KEY_ID` | both | unset | *secret*; required for `s3` |
| `LEKTO_S3_SECRET_ACCESS_KEY` | both | unset | *secret*; required for `s3` |
| `LEKTO_S3_PATH_STYLE` | both | `true` | Path-style addressing (Garage needs it) |
| `LEKTO_API_HOST` | API | `0.0.0.0` | Where the API listens |
| `LEKTO_API_PORT` | API | `8000` | `0`: the operating system picks a free port, which the log line `api started` names (for tests; the image's health check needs a fixed port) |
| `LEKTO_UPLOAD_MAX_SIZE` | API | `100MiB` | Largest upload; bytes or with unit (`50MB`, `1GiB`); a proxy's body limit must allow it |
| `LEKTO_REQUEST_MAX_SIZE` | API | `1MiB` | Largest body of every other request (JSON); larger ones get `413` |
| `LEKTO_UI_DIR` | API | unset; image: `/opt/lekto/ui` | The built web UI (`web/build`), served below `/ui`; `/` leads there. Must contain `index.html`; unset serves the API only |
| `LEKTO_FORWARDED_ALLOW_IPS` | API | unset; required with `LEKTO_COOKIE_SECURE=true` | Reverse proxies whose `X-Forwarded-For` is trusted (comma-separated). Secure cookies mean a TLS-terminating proxy in front of Lekto: name its address, or the per-source throttle sees only the proxy. `*` only if the proxy sets the header itself, replacing what clients send |
| `LEKTO_SECRET_KEY` | both | required | *secret*; 32 bytes base64 (`openssl rand -base64 32`); encrypts TOTP and webhook secrets and header values, the worker decrypts the latter to send. Keep it: without it they cannot be read. The development key is refused with secure cookies |
| `LEKTO_ADMIN_USERNAME` | API | unset | The first admin, created at API start while there is no active admin; set together with the password |
| `LEKTO_ADMIN_PASSWORD` | API | unset | *secret*; see above |
| `LEKTO_SESSION_IDLE_TIMEOUT` | API | `P1D` | A session ends when unused this long |
| `LEKTO_SESSION_MAX_AGE` | API | `P30D` | A session ends this long after sign-in; not shorter than the idle timeout |
| `LEKTO_COOKIE_SECURE` | API | `true` | `false` only for development over plain HTTP |
| `LEKTO_PUBLIC_URL` | API | unset | Where browsers reach Lekto (`https://lekto.example.org`); required with OIDC |
| `LEKTO_OIDC_ISSUER` | API | unset | OpenID Connect: set issuer, client id and client secret together or none; the issuer is `https` and compared exactly. Register `<LEKTO_PUBLIC_URL>/api/v1/auth/oidc/callback` as redirect URI |
| `LEKTO_OIDC_CLIENT_ID` | API | unset | see above |
| `LEKTO_OIDC_CLIENT_SECRET` | API | unset | *secret*; see above |
| `LEKTO_OIDC_SCOPES` | API | `openid profile email` | Must contain `openid` |
| `LEKTO_OIDC_DISPLAY_NAME` | API | `Single sign-on` | Name of the provider on the sign-in page |
| `LEKTO_OIDC_AUTO_CREATE` | API | `false` | Create a user at the first sign-in of an unknown provider account |
| `LEKTO_OIDC_USERNAME_CLAIM` | API | `preferred_username` | ID token claim that names such a user |
| `LEKTO_WEBHOOKS_PER_USER` | API | `20` | Webhooks a user may have |
| `LEKTO_WEBHOOK_SECRET_GRACE` | API | `P1D` | How long the old secret signs after renewing; the cleanup drops it afterwards |
| `LEKTO_WEBHOOK_TIMEOUT` | Worker | `10` | Seconds per delivery attempt (1 to 120) |
| `LEKTO_WEBHOOK_MAX_ATTEMPTS` | Worker | `10` | Attempts per delivery (1 to 50) |
| `LEKTO_WEBHOOK_RETRY_DELAY` | Worker | `30` | Seconds before the second attempt, doubling after, at most an hour |
| `LEKTO_WEBHOOK_DISABLE_AFTER` | Worker | `20` | Deliveries given up in a row until a webhook is switched off |
| `LEKTO_WEBHOOK_CONCURRENCY` | Worker | `4` | Deliveries at the same time |
| `LEKTO_MCP_ENABLED` | API | `true` | Serve MCP at `/api/v1/mcp` |
| `LEKTO_MCP_TEXT_MAX` | API | `20000` | Characters one `get_text` call and one piece of `GET /documents/{id}/text` return at most (1,000 to 1,000,000) |
| `LEKTO_WORKER_CONCURRENCY` | Worker | `2` | Jobs at the same time, see Worker |
| `LEKTO_WORKER_POLL_INTERVAL` | Worker | `1` | Seconds between looks for due jobs |
| `LEKTO_WORKER_SHUTDOWN_TIMEOUT` | Worker | `30` | Seconds running jobs get to finish on SIGTERM |
| `LEKTO_NODE_MAX_ATTEMPTS` | Worker | `3` | Attempts of a pipeline node that raises |
| `LEKTO_NODE_RETRY_DELAY` | Worker | `30` | Seconds before the second attempt, doubling after |
| `LEKTO_EVENTS_POLL_INTERVAL` | Worker | `1` | Seconds between outbox dispatches |
| `LEKTO_EVENTS_MAX_ATTEMPTS` | Worker | `10` | Delivery attempts of an event per subscriber |
| `LEKTO_CLEANUP_INTERVAL` | Worker | `3600` | Seconds between cleanups |
| `LEKTO_RETENTION` | Worker | `P7D` | Age of finished jobs, delivered events and webhook log rows to remove |
| `LEKTO_OCR_LANGUAGES` | Worker | `deu+eng` | Tesseract languages, joined by `+` |
| `LEKTO_OCR_TIMEOUT` | Worker | `600` | Seconds per document for OCR |
| `LEKTO_MEILISEARCH_URL` | both | unset | Without it there is no search (the API searches, the worker indexes) |
| `LEKTO_MEILISEARCH_API_KEY` | both | unset | *secret*; the master key or a key with access to the index |
| `LEKTO_MEILISEARCH_INDEX` | both | `lekto-documents` | The active index; a rebuild fills `<name>-rebuild` and swaps it in |
| `LEKTO_MEILISEARCH_TIMEOUT` | both | `30` | Seconds per request |
| `LEKTO_MEILISEARCH_TASK_TIMEOUT` | Worker | `120` | Seconds a write waits for its task |
| `LEKTO_SEARCH_LOCALES` | both | `deu+eng` | Languages of the documents, ISO 639-3 codes joined by `+` (index settings) |
| `LEKTO_SEARCH_SEMANTIC_RATIO` | API | `0.5` | Weight of the meaning against the words when a request does not say |
| `LEKTO_SEARCH_EMBED_TIMEOUT` | API | `5` | Seconds to wait for the embedding of a query, then words only |
| `LEKTO_SEARCH_MAX_TEXT` | Worker | `200000` | Characters of text per document in the index |
| `LEKTO_SEARCH_CHUNK_SIZE` | Worker | `1500` | Characters per section with a vector |
| `LEKTO_SEARCH_MAX_CHUNKS` | Worker | `8` | Sections with a vector per document |
| `LEKTO_SEARCH_RECONCILE_INTERVAL` | Worker | `21600` | Seconds between comparisons of index and database |
| `LEKTO_SEARCH_REBUILD_TIMEOUT` | Worker | `21600` | Seconds a rebuild may take |
| `LEKTO_LLM_BASE_URL` | Worker | unset | OpenAI-compatible endpoint with version path (`http://ollama:11434/v1`); set together with the model or neither |
| `LEKTO_LLM_MODEL` | Worker | unset | see above |
| `LEKTO_LLM_API_KEY` | Worker | unset | *secret* |
| `LEKTO_LLM_TEMPERATURE` | Worker | `0` | 0 to 2; 0 for repeatable answers; `none` sends none (for models that reject one, such as Claude Sonnet 5.5) |
| `LEKTO_LLM_SEED` | Worker | unset | Passed to the endpoint, if set |
| `LEKTO_LLM_TIMEOUT` | Worker | `300` | Seconds per request (`600` on a CPU) |
| `LEKTO_LLM_RESPONSE_FORMAT` | Worker | `json_schema` | `json_object` for providers without JSON schema support; the schema then goes as a message after the task (also for prompt caching where a provider puts the schema before the system prompt) |
| `LEKTO_LLM_INPUT_BUDGET` | Worker | `12000` | Characters of document text per request (a run of spaces counts once) |
| `LEKTO_LLM_MAX_TAGS` | Worker | `200` | Tags listed per request |
| `LEKTO_EMBEDDING_BASE_URL` | both | unset | OpenAI-compatible endpoint; set together with the model or neither (the worker embeds sections, the API embeds queries) |
| `LEKTO_EMBEDDING_MODEL` | both | unset | see above |
| `LEKTO_EMBEDDING_API_KEY` | both | unset | *secret* |
| `LEKTO_EMBEDDING_TIMEOUT` | both | `60` | Seconds per request |
| `LEKTO_EMBEDDING_DIMENSIONS` | both | unset | Length of the vectors (Qwen3-Embedding 4B: 2560; `snowflake-arctic-embed2`, `bge-m3`: 1024); required with Meilisearch and an embedding endpoint |
| `LEKTO_EMBEDDING_QUERY_PREFIX` | API | unset | Put before queries, for models that ask for it (`query:`; Qwen3-Embedding an instruction and `Query:`); `\n` stands for a line break |
| `LEKTO_EMBEDDING_DOCUMENT_PREFIX` | Worker | unset | Put before document sections, for models that ask for it; `\n` stands for a line break |
| `LEKTO_VLM_BASE_URL` | both | unset | OpenAI-compatible endpoint of a vision language model that reads a document's pages when a person asks for it (`POST /documents/{id}/vision`); the page images go there. Set together with the model or neither; off without. The API names model and endpoint in `GET /pipeline` |
| `LEKTO_VLM_MODEL` | both | unset | see above: a model that takes images and gives each line's box in pixels (measured with Claude Sonnet 5.5) |
| `LEKTO_VLM_API_KEY` | Worker | unset | *secret* |
| `LEKTO_VLM_TIMEOUT` | Worker | `1800` | Seconds for reading a whole document with the model (one page at most 300); that OCR's job lease grows with it |
| `LEKTO_CONFIDENCE_THRESHOLD` | Worker | `0.9` | A field passes from this confidence on |
| `LEKTO_CONTACT_SUGGEST_THRESHOLD` | Worker | `0.75` | An existing contact is suggested from this similarity on; not above the confidence threshold |
| `LEKTO_POOR_READING_THRESHOLD` | Worker | `0.08` | Share of unsure content words (below 60 % of Tesseract's confidence; noise left out, see the field checks) from which a value's place counts as poorly read, and the value is only suggested: the 20 content words nearest to it, else the page the OCR recognised. The default lies between good scans (up to 7 %) and broken ones (from 9 %) of a first sample; calibration in M18 |
| `LEKTO_DEFAULT_CURRENCY` | both | `EUR` | The currency of an amount in a document that shows no currency at all (ISO 4217), and of the `currency` filter in templates where they name none |
| `LEKTO_CLASSIFIER` | both | `scikit-learn` | The classifier trained from confirmed documents; `none` turns it off |
| `LEKTO_CLASSIFIER_MIN_EXAMPLES` | both | `20` | Confirmed documents before the first model is trained |
| `LEKTO_CLASSIFIER_RETRAIN_AFTER` | both | `25` | Documents confirmed since the last model before it is trained again |
| `LEKTO_CLASSIFIER_THRESHOLD` | Worker | `0.8` | A prediction this sure names its contact, type or tag |
| `LEKTO_NEIGHBOURS` | Worker | `5` | Similar confirmed documents that vote on a new one (needs the search index with embeddings); `0` turns them off |
| `LEKTO_LOGO_FETCH` | both | `false` | Fetch the logos of contacts from their own websites (worker; the API offers the button): HTTPS to public addresses only, see Logos. Off, Lekto never asks the web on its own |
| `LEKTO_RULES_PATTERN_TIMEOUT` | both | `0.2` | Seconds a regular expression of a rule may run per text or value (worker: rules; API: previews) |
| `LEKTO_RULES_MAX_TEXT` | both | `200000` | Characters of text rules look at (1,000 to 10,000,000) |
| `LEKTO_RULES_APPLY_MAX_DOCUMENTS` | both | `1000` | Documents per retroactive rule application (1 to 100,000) |
| `LEKTO_TEMPLATE_LOCALE` | both | `de` | Locale in which templates of rules and title patterns write dates and amounts (`datetime`, `currency`, `decimal`, an amount field as `3.650,00 EUR`); Babel's names, such as `de`, `en_US` |

## Tests

- `tests/unit` (marker `unit`): no external services.
- `tests/integration` (marker `integration`): need Postgres, Garage or Meilisearch or the OCR
  programs (Tesseract, Ghostscript). Which services apply follows the
  `LEKTO_` variables; a test skips itself if what it needs is not configured or not reachable.
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
