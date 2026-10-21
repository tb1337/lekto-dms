# lekto migration

Command-line client that takes a Paperless-ngx archive over into Lekto. It reads Paperless
through its REST API and writes into Lekto through the Lekto API, with an admin's API token. It
uses no back doors, so a complete migration also proves the API is complete. It is a separate
uv project (`lekto_migration`, Python 3.13; dependencies `httpx2` and `ruamel.yaml`) and not
part of the Lekto image.

A migration is an ingest: Lekto reads every original itself (OCR as always: a page's own text
layer stays, another program's invisible one is replaced, images are read), the migration plan
brings the classification, and Lekto's rules and everything else run as usual.

## Phases

| Command | What it does |
| --- | --- |
| `plan` | Reads Paperless and Lekto and writes the migration plan (`migration-plan.yaml`): what is taken over, and how. Run again, it adds what is new in Paperless and marks what is gone; what you wrote stays, and it asks before it writes. |
| `check` | The cold run: writes nothing. Lists what `prepare` would create and, for every document, what it becomes (and where each value comes from), or, if it was migrated, whether Lekto differs and what the alignment would change. Compares the texts of migrated documents; `--download` checks the files. |
| `prepare` | Creates in Lekto what the plan needs: users, contacts, document types, tags with their hierarchy, contact and type groups, fields with their options, shared spaces with their members. Required before `run`; in between, set Lekto up (rules, fields of types) as you like. |
| `run` | Takes the documents over and aligns the migrated ones. Refuses while the plan lacks Paperless objects (`plan`) or Lekto lacks what it names (`prepare`). Ctrl-C stops cleanly; run again to continue. |

`plan`, `prepare` and `run` show what they will do and ask; without a terminal they need `--yes`.

## The plan

Every Paperless object has an entry under its name (names compare without case): one target, a
list of targets, or `drop`.

```yaml
source: http://paperless:8000
target: http://lekto:8000

settings:
  currency: EUR                  # for amounts without a currency
  fallback_owner:                # Lekto user who uploads documents without an owner; empty: you
  deactivate_inactive_users: true
  take_over_added: true          # when it came in at Paperless becomes its receipt
  space_name: "Geteilt: {members}"   # {members}: every member of the space with their role
  text_threshold: 0.8            # check lists documents Lekto read fewer words of

documents:                       # which documents
  include: {added: {from: 2018-01-01}}
  exclude: {tags: [Privat]}

users:
  Tobias: {to: user, name: tobi}
  anna: [{to: user, name: anna, create: true}, {to: tag, name: Anna, create: true}]

correspondents:
  Telekom: {to: contact, name: Deutsche Telekom AG}
  Sonstiges: {review: Resolve the contact in Lekto}

tags:
  Rechnung: {to: document_type, name: Rechnung, override: true}
  bezahlt: {to: field, name: Bezahlt, value: true, type: boolean, create: true}
  Krankenkasse:
    - {to: topic, name: Krankenversicherung, create: true}
    - {to: tag, name: Gesundheit, parent: Privates, create: true}
  Inbox: drop

custom_fields:
  Betrag: {to: field, name: Betrag}
  Rechnungsdatum: {to: document_date, override: true}
  Kategorie:
    values:
      Auto: {to: tag, name: Auto}
      Haus: {to: topic, name: Wohnen}
  Versicherer: {to: contact, by_value: true, create: true}

storage_paths:
  Steuern: {to: tag, name: Steuern}

asn: {to: field, name: ASN}
```

- **Targets** (`to`): `user` (only for users; a user always has one), `contact`,
  `document_type`, `topic`, `tag`, `contact_group`, `type_group`, `field`, `space`,
  `document_date`. Any Paperless object can go to any target, and to several.
- `name`: the Lekto object. `create: true` lets `prepare` create it if Lekto lacks it; without
  it, a missing one is an error, so a typing error creates nothing.
- `value`: what a field (or the document date) gets from an object without a value of its own,
  a tag for example. A custom field brings its value, converted to the type of the Lekto field;
  `type` is the data type of a field `prepare` creates.
- `values` (custom fields): a target per value. `by_value: true`: the value is the name of the
  contact, type, tag, topic or group.
- `parent`: the tag above (tags, topics and groups nest); the first plan takes Paperless'.
- `review: true`, or a reason: every document with the object waits in Lekto's inbox (yellow)
  with the reason, the field it is about open; with `drop`, that field stays empty for a person
  to decide.
- **Conflicts**: a document has at most one contact, type, topic, date, space and value per
  field. The natural target sets it (a correspondent's contact, Paperless' date, the space the
  permissions need); a reinterpretation only fills what is empty, unless it has
  `override: true`; several competing on equal terms leave it as it would be without them.
  `check` shows each conflict.
- A **space** target names a shared space (names are unique among them): an existing one is
  used as it is (its members see the documents), a new one is created with the uploaders of
  its documents as editors. Personal spaces are not named in the plan: a document without
  further permissions and without a space goes to its uploader's. A **group** puts the
  document's contact (or type) in it. A **topic** is set after the pipeline (the upload carries
  none), and enabled at the contact. A field bound to document types only takes values of
  documents of those types.
- **Selection** (`documents`): `include` needs every criterion, `exclude` one. Criteria: `id`,
  `asn` (a list or `{from, to}`), `title`, `original_file_name` (text, `{contains}`,
  `{matches: <regex>}`), `mime_type`, `correspondent`, `document_type`, `storage_path`, `owner`
  (a name or list; `null` for none), `tags` (a list, `{any}`, `{all}`, `{none}`),
  `shared_with`, `created`, `added`, `modified` (`{from, to}`), `has_notes`, `custom_fields`
  (`{<name>: true | false | <value> | [<values>] | {from, to}}`).

## Defaults of the first plan

| Paperless-ngx | Lekto |
| --- | --- |
| Users | users by user name; missing ones created without password, role `user`; those inactive in Paperless deactivated at the end of a run |
| Correspondents, document types, tags | contacts, document types, document tags by name, tags below the tag above them |
| Custom fields | global fields: string/longtext → text, url → link, date → date, boolean → yes/no, integer/float → number, monetary → amount, select → choice; `documentlink` dropped |
| ASN | field `ASN` (number) |
| Storage paths | dropped |
| Document date, date added | document date; receipt (`created_at`), where the milestones of its file start |
| Owner, permissions | uploaded by the owner (none, or a deleted one: the fallback owner or you), in the uploader's personal space; with permissions, a shared space for every combination of members (the uploader and the writers edit, the readers read; groups resolved to their users), named by `space_name`, which must name the members (`{members}`; the `{shares}` of earlier versions is an error) |
| File | the original (not Paperless' archive PDF) |

Not taken over: notes (counted at each document; Lekto has no notes), Paperless' text (Lekto
reads every document itself), history, share links, saved views, workflows, mail rules and
accounts, documents in the trash, further versions of a file, matching rules. Files Lekto does
not take (anything but PDF, JPEG, PNG, TIFF) are listed with the reason.

## Aligning migrated documents

`run` (and `check`, which only shows it) compares three states of every value: what the
migration set last (the state file; for documents migrated before, the metadata of the upload
in Lekto's log), what Lekto has, and what the plan gives now. A value changes only where Lekto
still has the migration's; what a person or a rule changed since stays and is reported. Fields
and tags the migration never set stay as they are. The change (`PATCH /documents/{id}?confirm=false`)
confirms nothing and counts as no decision; Lekto's rules run. That is also how documents
migrated before the date added was taken over get it. A document deleted in Lekto is reported;
`run --reupload` uploads it again.

## Use

```sh
cd migration && uv sync
export LEKTO_MIGRATION_PAPERLESS_URL=http://paperless:8000
export LEKTO_MIGRATION_PAPERLESS_TOKEN=...     # or ..._TOKEN_FILE=/path
export LEKTO_MIGRATION_LEKTO_URL=http://lekto:8000
export LEKTO_MIGRATION_LEKTO_TOKEN=...         # an admin's API token, scope read_write

uv run lekto-migration plan       # write migration-plan.yaml; edit it
uv run lekto-migration check      # what would happen; nothing is written
uv run lekto-migration prepare    # create the master data in Lekto
uv run lekto-migration run        # take the documents over; Ctrl-C stops, run again to continue
```

In the devcontainer, `--env-file ../.devcontainer/dev.local.env` (before or after the command)
takes the `LEKTO_MIGRATION_*` settings of the development instance from that file of
`KEY=value` lines instead of the environment.

Options (all commands): `--plan` (default `migration-plan.yaml`), `--state` (SQLite file,
default `migration-state.sqlite`), `--report-dir` (default `migration-reports`), `--limit N`
(the first N selected documents), `--concurrency` (documents at a time, default 4); `--yes`
(`plan`, `prepare`, `run`: write without asking); `check --download` (download the originals:
checksum, type by content, duplicates: the same file in the space a document goes to or in one
its uploader is a member of, as Lekto counts them); `run --pipeline-timeout`, `run --reupload`. API keys
come from the environment (or a file) only and are never written to the plan, the state or the
reports.

The plan and the state file belong to one Paperless and one Lekto (if Lekto is reset, delete
the state file, too). The state maps every document to its Lekto document and records what the
migration set; an interrupted run continues where it stopped and a second run creates nothing
twice. Reports (`plan`, `check`, `prepare`, `run`, each as `.md` and `.json`) list every object
and document with what became of it, or why not. Exit codes: 0 fine, 1 problems or failures or
nothing written, 2 cannot go on (wrong key, unreachable server, a plan that cannot be used, a
phase missing), 130 stopped.

## Checks

```sh
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```

The tests run the client against stand-ins for both APIs (`lekto_migration/fake_paperless.py`,
`tests/fake_lekto.py`). The tests against the real API (in memory) are in the backend:
`backend/tests/unit/adapters/rest/test_migration_flow.py`.
