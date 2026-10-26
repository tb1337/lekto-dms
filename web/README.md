# lekto web

Web UI: a single-page app on top of the Lekto REST API, served by the API under `/ui`. It talks to
the API only (`/api/v1`), through a TypeScript client generated from the API's OpenAPI document.

Stack: SvelteKit 3 (Svelte 5, static adapter, no server-side rendering), Tailwind CSS 4,
shadcn-svelte (bits-ui), Paraglide JS (English and German), openapi-fetch, CodeMirror 6 (templates),
Vitest. Fonts (Geist, Geist Mono) are part of the build; no CDN.

## Commands

Run in `web/` (Node 24, pnpm as pinned in `package.json`):

```sh
pnpm install
pnpm dev             # Vite on :5173, /api proxied to the API on :8000
pnpm lint && pnpm format:check
pnpm check           # svelte-check
pnpm test            # Vitest (CI)
pnpm build           # static app in build/
pnpm e2e             # Playwright smoke test against a running API (local only)
```

The smoke tests (`tests/e2e`) run against the API serving the built UI. `smoke.spec.ts` creates a
user through the admin of the environment, signs in with password and TOTP, navigates, reloads and
signs out. `areas.spec.ts` signs in as that admin (without a second factor), opens every area
without a console error (a CSP violation is one) and creates and removes a contact, a space, a
webhook and an API token; `webhooks.spec.ts` creates a webhook on its page, tests, changes and
deletes it; `rules.spec.ts` does the same with a rule:

```sh
pnpm build
# backend/: the API with LEKTO_UI_DIR=../web/build and LEKTO_COOKIE_SECURE=false
LEKTO_ADMIN_USERNAME=… LEKTO_ADMIN_PASSWORD=… pnpm e2e
```

`LEKTO_E2E_URL` (default `http://127.0.0.1:8000`) names the API, `LEKTO_E2E_CHROMIUM` a Chromium
of another Playwright version instead of `pnpm exec playwright install chromium`.

For `pnpm dev`, start the API in `backend/` with `uv run lekto api` and
`LEKTO_COOKIE_SECURE=false` (plain HTTP). Open http://localhost:5173/ui/.

## PDF viewer and CSP

The viewer uses the legacy build of `pdfjs-dist` (the normal one needs `Map.getOrInsertComputed`,
missing in older browsers). The worker is bundled; the plugin `vite-pdfjs.js` serves and emits
wasm, standard fonts and CMaps under `/ui/pdfjs/`.
The Content-Security-Policy (`vite.config.ts`) allows `worker-src 'self'` and `style-src-attr 'unsafe-inline'` (pdf.js sets style attributes);
scripts, style elements and images stay `'self'` only: pdf.js draws on a canvas and creates no
blob or data URLs, previews come from the API, the TOTP QR code is inline SVG (checked in the
browser with a PDF holding a JPX image, M13).

## Template editor

Templates of rules and title patterns are edited with CodeMirror (`src/lib/templates/codemirror.ts`),
loaded with `import()` where a template is shown. The colours, the place of a completion and
where a value or filter goes are plain functions in `liquid.ts`, which the rule view uses too.
The editor sits in a shadow root: there CodeMirror adopts a constructed style sheet, which the
CSP lets through, instead of a `<style>` element, which it blocks. The page's styles do not reach
in (the editor's theme holds its colours), and bits-ui's focus trap does not see focus inside, so
a listener keeps `focusin` from the editor away from it. Component tests get a plain text area in
place of the editor (`tests/setup.ts`); `codemirror.test.ts` runs the real one.

## Inbox

`/ui/inbox` is the start page and the way in: documents are uploaded there only, and
everything new stands there until a person saw it or decided.

- **Upload:** the button opens `UploadDialog` (files chosen, on a phone through the system's
  picker with camera and photos, or dropped there); it asks for no space and no uploader:
  every upload lands in the uploader's personal space, and Lekto suggests where it belongs
  (the API keeps `space_id` and `uploaded_by` for scripts and the migration). Dropping files on
  the page uploads them at once as well; an overlay shows
  while files are dragged over it (not on a phone). A drop may hold folders, read in full
  and recursively through the browser's entries (`lib/intake.ts`, batched `readEntries`),
  without their structure; files of other types (only PDF, JPEG, PNG, TIFF go) and hidden
  ones (`.DS_Store`, hidden folders as one) are skipped. Three requests at a time
  (`lib/upload.svelte.ts`). The result (`UploadSummary`: uploaded, duplicates with a link to
  the document already there from the 409's `existing_document_id`, skipped with the reason,
  413 as too large, failures) stays until dismissed, in this browser only; the progress shows
  while files are on their way. `/ui/documents` has no upload.
- **Tabs** in `?tab=` (`lib/inbox-view.ts`): all that is open (none), new, review, intervene,
  processing, done; an unknown one counts as none. Each row (`InboxRow`) says where its
  document stands: in processing with its progress bar, yellow or red with the lane and why,
  new calmly with a marker and "Seen" (no call to act), done (the last 14 days) with how
  (confirmed or seen), when and by whom, and "Mark as new" for a seen one. "Mark all as
  seen" asks first. Events refresh the list, also while documents are processed. On a phone
  the tabs scroll sideways in their row, and the actions of a row are icons of 44 pixels.

The counter at the menu entry (`lib/inbox.svelte.ts`) shows everything open from
`/inbox/summary`, on the colour of the worst lane in it (grey with only documents in
processing); its label names what stands there. The tabs show the same counts. The summary is
fetched again after events and when the window comes back into view.

## Documents and search

`/ui/documents` is the archive: it lists the documents and, with words in `?q=`, searches them
(`/documents/search`, with snippets), with the same filters (`lib/filters.ts`: contact, type,
tags, contact and type groups, topics, space, a field with a value; tags, groups and topics as
chips, several topics meaning one of them); there is no search page of its own. It shows no
lanes and no progress: a document that stands open in the inbox (`in_inbox`) carries "In the
inbox", a link to the inbox tab it stands under (`InboxMark`); the document view keeps the lane
in its head. A row or card asks for the preview only of a document with page images
(`page_count`). The field in the
header leads there; on narrow screens its icon opens the view with the field focused
(`#search`). `?sort=` holds the sort: a search by relevance, a list by the newest document date
unless chosen otherwise; the last choice of each, and grid or list (grid by default), stay in
this browser (`lib/listing.ts`). An admin's choice to include all users is a setting of the
user menu (`lib/scope.svelte.ts`), kept in this browser too and shown at the avatar; documents,
search, the inbox with its counter, rules and the counts at the master data follow it. Every
`localStorage` access is guarded: without storage the defaults hold.

## Header

The app's header holds the menu, the wordmark, the search, language, theme and the account menu
(`AppShell`). On a phone (below `sm`) language and theme are groups of the account menu instead
(`LanguageChoices`, `ThemeChoices`, which the header's own menus use too); the sign-in page keeps
both menus at every width.

## Master data

`/ui/admin/master-data` (admins) has four tabs in `?tab=`: contacts, document types, tags,
fields; an unknown one is the first. Each has a search in this browser (`lib/master-search.ts`:
contacts also by aliases and identifiers) and its button to add. The Tags tab holds every kind
of tag (`TagsPanel`, `lib/tag-kinds.ts`): a filter by kind in `?kind=`, one section per kind
with its tree, the collapsed sections remembered in this browser, and per tag its usage as a
link (documents; a contact group's contacts and a type group's types, which the contact and type
lists filter by `?group=` and `?topic=`). A new tag without a kind asks for it first.

On a phone (below `sm`, `lib/phone.svelte.ts`) a whole row opens the editor (`MasterRow`), and
the editors fill the screen with a bar on top (`EditorShell`); wider, the editors are dialogs
whose footer stays while the body scrolls. The long editors have tabs of one height
(`EditorShell` `tabs`): a contact's General and Identifiers, a document type's General and
Fields, a field's General and Document types; each tab counts what it holds. The help of a field
opens from an info button beside its label (`InfoHint`, `HintLabel`). A contact's identifiers
stand one per line under their kind, with a search; a line opens with its arrow
(`IdentifiersEditor`), and when the API refuses a value (it quotes it) saving opens that tab and
line with the message. Its other spellings are chips (`ChipInput`). The contact editor puts the
logo beside the name on a phone, uploading and fetching below them (`ContactLogoEditor` with
`beside`). Deleting is in the editors. Groups and topics are
picked in a sheet or dialog over the editor (`TagPicker`). There, in the document's tag input
and in its contact, type and topic fields, an admin's search that finds nothing of the kind
named so offers to create it: the kind's full dialog over the page or the current one, the
name filled in (`masterDataDialogs.create`, `MasterDataCreate`); what it makes is chosen,
closing it chooses nothing. Nothing is made from the name alone.

Icons come from Lucide in the own build, each its own file loaded when it is shown. Chips and
type icons draw the 170 offered first from a small map (`lib/icons/curated-modules.ts`, which a
test keeps equal to `curated.ts`); the map of all 1,866 (about 43 KB gzip) loads only with the
icon picker's panel (`IconPickerPanel`, with the search and its words) or for an icon beyond
those (`lib/icons/load.ts`).

## Profiles

Users are shown by their display name, else their username (`userLabel`, `userName` in
`lib/masterdata.svelte.ts`; members of a space carry theirs). `ProfileForm` edits a profile:
the own one in the settings (`/auth/me/profile`), another user's for admins in the user
dialog (`/users/{id}/profile`): display name, other names, birth date, e-mail and the person's
own numbers in `IdentifiersEditor` with `kinds={PERSON_KINDS}`. In the contact dialog
(`withUsers`) a customer or personnel number names the user it belongs to. The facts beside a
document list the persons it names for its editors (strength and kinds of evidence; a click
marks their names and numbers).

## Spaces

Rights hang on the space a document lies in, as the caller's role there (`SpaceOut.role`:
`read` sees the green documents, `edit` every document and the space's rules, members and
name); admins edit every space. `lib/permissions.ts` keeps the UI to what the API allows.
`/ui/spaces` lists the caller's spaces, their personal one first ("Personal" for its user, its
user's name for others, `spaceLabel`), with the members; admins also see the spaces they are no
member of. `SpaceMembers` adds members with a role, changes and removes them; the user of a
personal space and the last editor of a space stay editors, and only its user (or an admin)
chooses the members of a personal space. Members come with their names and whether they are
active (`SpaceOut.members`): a deactivated member takes no new role, an editor removes them.
Every member leaves a space themselves (`canLeaveSpace`), apart from the user of a personal
space and the last editor. A personal space is neither renamed nor deleted, a shared one only
while empty. Editors describe a space (`SpaceDialog`, `PATCH /spaces/{id}` with `SpacePatch`),
a personal one too: the language model reads what belongs in it when Lekto suggests a space
(another user's personal space only by its user's name).

The document's head names its space and who else sees it. Moving goes into a space the caller
edits, or hands the document over into another user's personal space ("Hand over to Anna",
`spaceOptions`); the same choice stands where a document is confirmed into a space and in a
rule's "File into space". The hand-overs come from the users list (`personal_space_id` of
`GET /users`), as a hand-over needs no membership. A rule belongs to
a space the caller edits (their personal one by default) or, for admins, is global; it files
where whoever saves it may file, and a space's rules run when a document arrives there. Editing
a rule may move it ("Applies to", `lib/rules/places.ts`): the save sends `scope` and `space_id`
with the content, and the rule's version list says where a version moved it.

Deleting a user (admin › users) asks for the spaces they leave behind (`UserDeleteDialog`,
`lib/user-removal.ts`, from `GET /users/{id}/removal`): per space "Delete with the user" (empty),
"Move the documents, then delete" with the space they go to, or "New editor, the space stays"
with the user; one click deletes the user and settles all of them in one request.

When Lekto suggests a space that shows the document to others (the judge's open `space` check
with a `suggestion`), the inbox row says so ("Suggested: Haushalt (visible to anna)",
`lib/space-suggestion.ts`) and the document form starts its space choice at the suggestion;
confirming it sends `accept_suggestions: true`, another choice its `space_id`, the current space
keeps it. The log names the spaces of the signals, the spaces a document went through
(`apply_rules` output `spaces`) and the rules of a space it arrived in.

## Document view

`/ui/documents/{id}` serves the inbox and the document list (`/ui/inbox/{id}` leads there with
`?from=inbox`, which keeps the place among the inbox's documents) with the tabs details,
content, metadata and log (`?tab=`). From the desktop width on (`lg`) the view fills the window
and only its cards scroll; on narrow screens the page scrolls.

Opening the view reports the document seen (`PUT /documents/{id}/seen`), from wherever it was
opened, and again when the open document turns green (seen while it is processed does not
count); the counter follows. Opened from the inbox, the inbox is loaded again for every
document shown, and a document that leaves it while open keeps its place there
(`keepPlace`). After confirming, the view offers to open the inbox's next document that waits
for a decision, yellow or red, the first before it if none follows, never a new one or one in
processing (`nextDecision`); without one, back to the inbox.

- **Details:** the archive PDF with PDF.js; until the archive exists (the text is still being
  recognised), the page images from the API stand in, and before they exist the original of a
  PDF (an image shows nothing yet; `viewerSources`: nothing is asked for that cannot be there).
  Both are shown by `PageViewer`: the pages side by side, wrapping into rows, their width
  following the zoom (100 % is a page's printed size), so the zoom decides how many stand in a
  row. The layouts one page, two pages
  (the start; one on a narrow screen) and overview (four in a row, as far out as the zoom
  goes) are buttons, marked once zooming reaches them (`lib/viewer/zoom.ts`). Ctrl or ⌘ with
  the wheel, a pinch on a trackpad, Safari's gestures and two fingers zoom around the pointer
  (`lib/viewer/gestures.ts`); a double click enlarges a page and goes back; the keys + − 0.
  Pages are scaled while the zoom moves and drawn anew once it rests. A field with a quote
  marks it on the page while hovered or focused (the places come from `/review`, the space's
  editors and admins), a click on its page jumps there; so does a code from the content tab.
- **Filing** (`FilingBox`, `lib/filing.ts`): where the document lies and who sees it. While
  the judge's space check waits for a person, a yellow box at the top of the form, above the
  basics: where it lies, a lead sentence ("Lekto schlägt vor, das Dokument an Anna Leider zu
  übergeben." or, when the signals disagree, "Wähle, wohin es gehört."), the choices as radio
  cards built from the check's candidates (the suggestion first, the other spaces named,
  leaving it where it lies), each with what speaks for it (the model, the recipient it read,
  "5 von 5 ähnlichen Dokumenten liegen dort", the classifier's probability) and what it changes,
  plus "Another space" with the caller's other targets; a suggestion is chosen from the start,
  a disagreement chooses nothing. Named people who would not see it there stand in a blue note
  (`unseen_by`). Above "Confirm" a line says what the choice does: "Erst wählen, dann
  bestätigen." (the button waits), a hand-over as a warning, a move with its new readers;
  staying says nothing. With nothing to decide, a calm box below the fields: space, members
  with their roles (readers once the document is green), who uploaded it, when a person decided
  the space (`space_confirmed_at`), and "Move" (the head's move dialog).
- **Content:** the text as it is set, page by page, and beside it the facts and codes
  (`FactsPanel`, from `/facts`). Text and facts are asked for once the document has its text
  (`hasText`: `parse` done in the first run; a later run keeps the text of the one before), not
  while it is processed for the first time or failed before its text was read (409).
- **Metadata:** the files from `/files`: size, SHA-256, a PDF's information and XMP, an
  image's EXIF.

## API client

`openapi.json` is the API's document, checked in; a backend unit test fails while it differs from
the code. After an API change:

```sh
cd backend && uv run python -m lekto.composition.openapi ../web/openapi.json
cd web && pnpm gen:api   # writes src/lib/api/schema.ts
```

## Layout

| Path                           | Content                                                                         |
| ------------------------------ | ------------------------------------------------------------------------------- |
| `src/lib/api`                  | Client, `fetch` with session cookie and CSRF header, problem details            |
| `src/lib/session.svelte.ts`    | The signed-in user and the CSRF token, in memory                                |
| `src/lib/components`           | App shell, documents, dialogs, PDF viewer; `ui/` holds the shadcn-svelte ones   |
| `src/lib/components/document`  | The document view: head, fields, content (Markdown), log, prompt                |
| `src/lib/components/templates` | The template field, the template editor (sheet), the reference document picker  |
| `src/lib/templates`            | Liquid colours and completions, the CodeMirror editor, the values templates see |
| `src/lib/i18n.ts`              | Language switch, date, number and money formats                                 |
| `src/lib/reasons.ts`           | The API's reasons with codes in the user's language (`reason_<code>` messages)  |
| `src/lib/periods.ts`           | Periods in ISO 8601 (`2026-Q2`, `2026-W17`), read also in German forms          |
| `src/lib/listing.ts`           | Sort and grid or list of the document view, remembered in this browser          |
| `src/lib/scope.svelte.ts`      | An admin's choice to include all users, remembered in this browser              |
| `src/lib/permissions.ts`       | What the UI offers by role in a space: edit, move, hand over, members, rules    |
| `src/routes`                   | `login`, the app pages in `(app)`; `(app)/dev/components` in development only   |
| `messages/{en,de}.json`        | All texts; a test fails on raw text in markup and on missing keys               |
| `tests/`                       | Tests across files (messages, raw text); `e2e/` the Playwright smoke test       |

Imports use `#lib/…` (package `imports`) with the file extension.
