# Lekto design system

This document is binding for the web UI. Every page, component and text in `web/` follows it.
`CLAUDE.md` links it. `.idea/architektur.md` describes what the views do. This document says how
they look and how they are used. Where the two seem to disagree on looks, this document wins.

**Changing a rule:** first a decision (Tobi), then a change of this document, then the code, in
that order. A change that needs something this document does not cover adds it here in the same
pull request. "The component was already like that" is not a reason to keep a deviation.

**Origin:** the design direction "Papier" (08.10.2026), smoothed after the review of 26.10.2026
(issue #167). That issue revised the earlier decisions on tab looks, chip shapes, the round "+",
the document card, the inbox mark, the navigation breakpoint, "Sichern", footer order, phone
editors, list rows, page widths, checkboxes, date fields, "enabled" wording and the form of
address.

## Principles

1. **One system.** A need is met by an existing component or token. If none fits, extend the
   component (a variant, a size) and document it here. A one-off copy is not allowed.
2. **Tokens only.** Colours, font sizes, radii and shadows come from `src/app.css`. No hex
   values, no Tailwind palette colours (`red-600`, `zinc-*`), no arbitrary values (`text-[13px]`,
   `rounded-[3px]`) outside the [exceptions](#exceptions).
3. **Quiet paper, one accent.** The ground is warm paper white (dark: deep green-grey). Petrol is
   the one accent: primary actions, links, focus. Lane colours mean state, nothing else.
4. **State is never colour alone.** A lane, a deadline or a check always shows an icon and a word
   as well.
5. **The phone is a first-class screen.** Every page works at 390 px without sideways scrolling.
   Targets are 44 px. Nothing depends on hover.
6. **Same thing, same look, same place.** The same action has the same name, the same component
   and the same position on every page.

## Tokens

All tokens are defined in `src/app.css` (`:root` and `.dark`) and mapped to Tailwind in
`@theme inline`. Every colour pair used for text meets WCAG AA (4.5:1) in light and dark mode.
A new token needs a value for both modes and that contrast.

### Colour roles

| Token (Tailwind)                                                          | Use                                                                                                                                  |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `background`, `foreground`                                                | Page ground and body text                                                                                                            |
| `card`, `card-foreground`                                                 | Cards, rows, inputs                                                                                                                  |
| `popover`                                                                 | Menus, popovers, dropdowns                                                                                                           |
| `surface`                                                                 | Neutral ground behind panes: the document viewer, field groups                                                                       |
| `muted`, `muted-foreground`                                               | Quiet fills (switch bars), secondary text                                                                                            |
| `secondary`, `accent`                                                     | Secondary buttons, hover fills                                                                                                       |
| `primary`, `primary-foreground`                                           | Primary button, selected state, focus ring (`ring`)                                                                                  |
| `brand`                                                                   | Petrol as text: links, the logo, the active tab. **The only link colour** (not `text-primary`)                                       |
| `panel`                                                                   | The tinted panel of the sign-in page and selected list entries                                                                       |
| `destructive`                                                             | Destructive actions and errors                                                                                                       |
| `border`, `input`                                                         | Lines and field edges                                                                                                                |
| `lane-green`, `lane-yellow`, `lane-red`, `lane-running` (+ `-foreground`) | Document state (done, review, intervene, processing) and anything that shares its meaning: deadline near or passed, success, failure |
| `note`, `note-foreground`                                                 | Notes and tips                                                                                                                       |
| `chart-1` … `chart-5`                                                     | Charts on the page "System" only                                                                                                     |
| `tpl-*`                                                                   | Liquid template highlighting only                                                                                                    |
| `mark-edge`, `mark-light`                                                 | The edge of a mark on a page image (`.mark-glass`)                                                                                   |

**Lane tones:** a mark of a lane (badge, chip, step of the processing band, counter) has the lane's
ground, its text in the lane's foreground, and a border in the foreground at low opacity. In light
mode there are no dark fills. One map, `tones.ts`, turns a lane or tone into these classes. Nobody
writes the classes by hand.

Tags have their own palette (twelve colours tuned for both modes, or an own `#rrggbb`). `chipLook()`
in `lib/chips.ts` draws it. The text follows the contrast.

## Typography

Fonts: **Geist** (UI) and **Geist Mono** (identifiers, URLs, templates, the text pane), both part
of the build.

The scale is defined in `@theme`. Use these steps only:

| Step (class)  | Size                     | Use                                                                      |
| ------------- | ------------------------ | ------------------------------------------------------------------------ |
| `text-title`  | 1.75rem, semibold, tight | The page title (`<h1>`), only through `PageTitle` (in `PageHeader`)      |
| `text-figure` | 1.875rem, semibold       | A big number on a stat card                                              |
| `text-lg`     | 1.125rem, semibold       | A section of a page (`<h2>`), through `SectionTitle`                     |
| `text-base`   | 1rem                     | Reading text, dialog titles                                              |
| `text-md`     | 0.9375rem, semibold      | The heading of a card or pane: `Card.Title`, `SectionTitle size="card"`  |
| `text-sm`     | 0.875rem                 | Default UI text: rows, fields, buttons                                   |
| `text-meta`   | 0.8125rem                | Secondary lines, dense panels (system, processing), small buttons        |
| `text-xs`     | 0.75rem                  | Captions, badges, the eyebrow                                            |
| `text-micro`  | 0.6875rem                | Marks on images (page count), counters in pills                          |
| `text-nano`   | 0.625rem                 | The smallest marks: legends of matrices and files, the smallest initials |

- **Eyebrow** (small uppercase label above a group, e.g. "LENSES", "ZEITRAUM"): the `Eyebrow`
  component (`text-xs font-medium uppercase tracking-wide text-muted-foreground`).
- **Headings in order:** one `<h1>` per page (`PageHeader`), then `<h2>`, then `<h3>`. Do not
  skip a level for the sake of looks: `SectionTitle` and `Card.Title` take a `level` apart from
  their size.
- **Numbers** in tables, counters and durations use `tabular-nums`. Durations do not wrap
  ("4,2s", "1m 3s").
- **Long words** (German compounds) break with hyphens: titles use `hyphens-auto` and `<html lang>`
  follows the UI language. A title is never cut mid-word without hyphenation.

## Radius, borders, shadows

| Role                                                     | Class                       | Token                         |
| -------------------------------------------------------- | --------------------------- | ----------------------------- |
| Buttons, inputs, selects, text areas, menus, popovers    | `rounded-xl`                | `--radius-xl`                 |
| Cards, dialogs, sheets, panes, empty notes               | `rounded-2xl`               | `--radius-2xl`                |
| Chips, badges, `Segmented`, switches, avatars            | `rounded-full`              |                               |
| Small marks inside a component (code thumb, bar segment) | `rounded-md` / `rounded-sm` | `--radius-md` / `--radius-sm` |
| The checkbox, swatches of a legend                       | `rounded-xs`                | `--radius-xs`                 |

All radii come from `--radius`. `rounded-3xl`, `rounded-4xl` and arbitrary radii are not used.

**Borders:** one hairline, `border` in `border-border`. Cards use `border`, not `ring`. Dashed
borders mean "empty" or "add": `EmptyNote` and the dashed "+ …" chip.

**Shadows:** cards have none. Popovers, menus and dialogs use the component's shadow. Marks on a
page image use `.mark-glass`; a pinned page of the viewer uses `shadow-pinned`. No other shadows.

**Dividers:** `ui/separator`, not hand-built `h-px`/`w-px` elements.

## Spacing and layout

- **Page:** `flex flex-col gap-6` from the header down. Sections inside a page use `gap-3` between
  their title and content.
- **Card padding:** `Card` sizes only: `row` = `p-4` (an item of a list), `sm` = `p-3.5` (dense
  panels: facts, relations), `md` = `p-5` (default), `lg` = `px-5 py-4`, `sm:px-6` (the sections
  of the system page), `flush` (the card's rows or parts pad themselves). Hand-built paddings
  are not used.
- **List rows:** `Card` with `size="row"`, at least 56 px tall.
- **Breakpoints:** Tailwind defaults: `sm` 640, `md` 768, `lg` 1024, `xl` 1280, `2xl` 1536 px.

### Page frame

`AppShell` holds every signed-in page. Each page starts with `PageHeader`:

- **Back link** (optional, detail pages): `BackLink`, above the title. It leads to the list the
  page came from, with that list's state: lens, filters, search and sort.
- **Title**: `PageTitle`, the `<h1>` in `text-title`, optionally followed by a count or a badge
  (lane). A long word breaks with a hyphen; one that cannot (a file name) breaks anywhere.
- **Subtitle** (optional): one line in `text-sm text-muted-foreground` under the title.
- **Actions**: right of the title, at its height. The primary action of the page is last
  (rightmost). On the phone, a page action may become an icon button. It keeps its label as
  tooltip and `aria-label`.

The header shows **while loading and after an error** (`Loading`, `LoadProblem` below it). The title shows a skeleton or the generic
name of the page ("Regel"), never "Edit " with an empty name.

### Page widths

| Width    | Max     | Class        | Pages                                       |
| -------- | ------- | ------------ | ------------------------------------------- |
| Wide     | 1600 px | `max-w-wide` | Documents (`/documents`), the document page |
| Standard | 1040 px | `max-w-page` | Every other page, settings included         |

`AppShell` sets the width: a page marks itself `data-wide` (fills the window) or `data-roomy`
(wide, scrolling) to get the wide one.

Content inside a standard page may be narrower for reading (a form column), never the page itself.
From desktop width the document page fills the window and scrolls only inside its panes. On the
phone the page scrolls.

## Navigation

- **Menu:** two groups divided by a line. _Work_: Posteingang · Dokumente · Spaces · Regeln ·
  Webhooks. _Administration and operation_: Stammdaten · Nutzer · System, the system at
  the outer right. The rights stay (master data and users for admins only).
- **From `lg` (1024 px):** the menu stands in the header. Below `xl` (1280 px) the second group
  goes behind "Mehr" (a dropdown), from `xl` it stands in the header too.
- **Below `lg`:** a sheet from the right, 320 px wide. Its button is the rightmost item of the
  header (thumb corner).
- **Start page:** the overview at `/`, reached by the logo; it has no menu entry.
- **Header items:** logo (favicon icon before the wordmark "lekto"), menu, search (the field where
  the header has room, `searchPlaces`: from `2xl`, for admins from 1720 px; otherwise the
  magnifier), user menu (avatar).
- **User menu:** name and role, the admin switch "Alle Nutzer einbeziehen", language and appearance
  (`LanguageChoices`, `ThemeChoices`, each a `Segmented`), settings, API documentation, sign out. On the phone (below `sm`) the sheet
  holds all of it: the header shows only logo, magnifier and menu button.
- **Inbox counter:** a badge on the menu entry, coloured by the worst lane it holds.

## Components

The primitives live in `src/lib/components/ui` (shadcn-svelte on bits-ui, adapted to these
tokens). The app's own components live in `src/lib/components`. Use them as listed here. Before
building something, look here and in `/dev/components`.

### Buttons

`Button` (`ui/button`). Buttons are rectangles with rounded corners (`rounded-xl`), like inputs.
Chips and badges are pills; a pill is never a button that starts an action.

| Variant       | Use                                                               |
| ------------- | ----------------------------------------------------------------- |
| `default`     | The primary action. At most one per view (page, dialog, card)     |
| `outline`     | Secondary actions next to a primary one; actions in a page header |
| `secondary`   | Quiet actions inside cards and panels                             |
| `ghost`       | Toolbar and row actions, "Abbrechen"                              |
| `destructive` | Delete, remove, revoke                                            |
| `link`        | Text actions inside running text ("Alle anzeigen")                |

| Size      | Height | Use                                      |
| --------- | ------ | ---------------------------------------- |
| `default` | 40 px  | Pages, headers, toolbars, dialog footers |
| `sm`      | 32 px  | Rows and cards (desktop)                 |
| `lg`      | 48 px  | The sign-in page only                    |
| `inline`  | text   | A button that reads as a word in a line  |

On the phone every button is at least 44 px tall (see [Touch targets](#touch-targets)). The
component handles this. Pages do not add `h-11` by hand.

**Icon buttons:** `IconButton` only. It takes a `label` (its tooltip and `aria-label`), a variant
and a size (`default` 40 px, `sm` 32 px), optionally a shorter `hint` as tooltip. Spread a menu
trigger's props on it to open a menu. Icon buttons are rectangles like every button. There is
no round "+". Plain `<button>`s are allowed only for whole-row targets and chips, never as
look-alikes of `Button`.

**Menus:** several actions of one object go into a menu: "…" for the rest, "Herunterladen" for
formats, the sort as `SortMenu`.

**Pen:** in every list whose entries have an editor, `EditButton` is the last column behind a
divider.

### Fields

- **`Input`**: `rounded-xl`, 44 px tall, `bg-card`, `border-input`. `Textarea`, `Select`,
  `SearchSelect`, `DateInput` and `SearchField` share its look through `ui/field-look.ts`
  (`FIELD`, `FIELD_HEIGHT`, and `FIELD_FRAME` for a frame around an input).
- **Label:** `Label`, or `HintLabel` when the field has help (info button beside the label, see
  [Help](#help-and-tooltips)). Every field has a label.
- **Errors:** `Field.Error` under the field, tied to it with `aria-describedby`.
- **`Select`**: a short, fixed list. On desktop a list in the style of the other pickers, on the
  phone the system's native picker.
- **`SearchSelect`** (one of many by searching: contact, document type, topic), looking like a
  `Select`. A popover on desktop; on the phone a sheet from the bottom (`PhoneSheet`) named by
  its `title` ("Kontakt wählen"), with a close button and rows of 48 px; a choice closes it
  (Tobi, 28.10.2026). Admins can create from the search (`CreateOffer`).
- **`SearchField`**: every search input, in pickers, lists and pages alike. The header search and
  the document search are `SearchField`s inside a form.
- **Dates:** `DateInput` (the bits-ui date picker: day, month and year to type, a calendar
  beside them), in the UI language; its value is the API's day (`2026-10-26`). Not
  `<input type="date">`, which follows the browser language. `PeriodInput` handles periods.
- **Tags of every kind:** `TagPicker`. One field with the chosen chips and a dashed "+ …" chip. The
  choice opens as a popover on desktop and as a sheet from the bottom on the phone.
- **Free values as chips** (other spellings, other names): `ChipInput`.

### Checkboxes, radios, switches

- **`Choice` / `ChoiceBox`** (`ui/choice`): every checkbox and radio. A native input
  (`appearance-none`), drawn from the tokens: `border-input`, checked in `primary`.
  `no-raw-choice.test.ts` enforces it.
- **`Switch`**: on/off that takes effect at once (a rule active, a webhook active, a setting). A
  switch is never shown together with a badge that says the same thing.
- **`ColorPicker`**: its own `radiogroup` of swatches. **`IconPicker`**: the Lucide picker.

### Chips

`Chip` is the one chip: a pill, `md` 32 px (`h-8`) or `sm` 24 px, icon and name, optionally
removable (`onremove`, a ✕ with a hit area of 44 px on the phone) or toggleable (`pressed`:
`aria-pressed`; on, the selected look and a bolder name, no check, at the width it has off, so
that the chips beside it stay: "Steady layout"). Its variants:

| Variant    | Use                                                                                                      |
| ---------- | -------------------------------------------------------------------------------------------------------- |
| `neutral`  | Free values (spellings), search words                                                                    |
| `outline`  | Groups (contact and type groups), quiet values                                                           |
| `selected` | What is chosen: active filters, a toggle that is on (`bg-panel`, text `brand`, a 1 px edge `primary/45`) |
| `add`      | The dashed "+ Gruppe" / "+ Thema" / "+ Name" that opens a picker                                         |

Tags and topics in their colours (`chipLook()`) are `TagChip`, drawn in the same shape. All chips
are pills, topics included. The field a chip stands in names its kind. `TagChips`, `GroupChips`,
`FacetChips` and `ChipInput` render `Chip` or `TagChip`.

### Badges

`Badge` (`ui/badge`) shows a state or a short fact. It is never a button. Its tones come from
`tones.ts`, shared with every lane mark:

| Tone                                | Use                                                                                              |
| ----------------------------------- | ------------------------------------------------------------------------------------------------ |
| `green`, `yellow`, `red`, `running` | Lane and state ("Erledigt", "Prüfen", "Eingreifen", "In Verarbeitung"; "Aktiv"); with icon       |
| `yellow` without icon               | A caveat that matters: "Unsigniert"                                                              |
| `green`, `muted` without icon       | A recommendation ("Übernehmen empfohlen" `green`, "Verwerfen empfohlen" `muted`): its words tell |
| `note`                              | Neutral information with meaning ("Persönlich", scope, kind)                                     |
| `muted`                             | Plain facts ("+3", counts, "Pausiert", read only)                                                |
| `primary`                           | What is marked as chosen: the current version, a suggestion                                      |
| `outline`                           | A person or an owner; the space of a foreign document                                            |
| `default`                           | The solid accent; not used on pages so far                                                       |

Sizes: `sm` 20 px (in rows, `text-xs`, the default), `md` 24 px (in headers), `lg` 28 px (the
lane of a document in its row or head). `LaneBadge` is `Badge` with the lane tone. Hand-built
pills are not used.

`VolumeMeter` shows how loud something is as three rising bars (`muted-foreground` on `border`),
always beside a text that says it in words (`aria-hidden`): how often a webhook event comes for
one document ("1×", "2–7×", "≈ 13× je Verarbeitung"), with a line under the list that adds up
the chosen events.

### Tabs and switches

Two components that **look different on purpose**:

- **`TabBar`**: the tabs of a page (inbox lanes, document, master data, system). Links that change
  the URL. **Underline tabs:** text in `muted-foreground`, the current tab in `foreground` with a
  2 px `brand` underline. A bottom border runs across the bar. It scrolls sideways on the phone
  with a fade at the cut edge. Counts and dots sit beside the label.
- **`Segmented`**: a choice of how to show something (pages, grid/list/stream, text/pages,
  form/facts, period quick picks, language, appearance), and in a form a choice among two or
  three short options that changes what follows (a webhook's trigger and body). A grey bar with
  the choice on a light pill that slides over (`motion-safe`, not on first show). Sizes: `md`
  40 px, `sm` 32 px; 44 px on the phone. With icons only (`names="hidden"`) every option has a label for its tooltip.
  Where it is wider than the room (a phone, five options with counts), it scrolls sideways as the
  `TabBar` does, the chosen option in view and a fade at the cut edge; it never widens the page
  (Tobi 29.10.2026).

No other tab or segmented look exists. `AutomationTab` and `PeriodFacet` use `Segmented`.

### Cards

`Card` (`ui/card`): `rounded-2xl border bg-card`, sizes `row`, `sm`, `md`, `lg`, `flush` (see
[Spacing](#spacing-and-layout)); `as` picks the element (`li`, `section`, `article`, `form` …),
`cardVariants` draws the look on an element that cannot be a `Card`. `Card.Title` renders a heading (`<h2>` by default, `level` to
change it) in `text-md`. `Card.Description` is `text-sm text-muted-foreground`. Hand-built
`div`s with border and radius are not used.

### Lists

Lists of items (rules, webhooks, spaces, users, master data) are rows in one card, or cards in a
column. Each row has:

1. **Leading** (optional): avatar, icon or thumbnail.
2. **Title**: a link to the detail page, or the opener of the editor where there is no detail page.
   Where the row has a detail page, the title's link takes the whole row (on the link
   `after:absolute after:inset-0`, the row `relative`); the controls of the row stand above it
   (`relative z-10`).
3. **Secondary line**: `text-sm text-muted-foreground`, with badges at the title.
4. **Trailing**: at most the `Switch` (where there is one) and the `EditButton`. Counts may stand
   before them as links. A space's row keeps its members and "Verlassen" as icon buttons: they
   have no detail page to go to.

**Delete, test, rotate secret, log and other actions live on the detail page or in the editor,**
not in the row.

**Choosing many** (the open identifiers, Tobi 27.10.2026): a list whose items are decided many
at once puts a `ChoiceBox` at the start of each row and one in its head that chooses the page.
**The chosen look**, in one place: a chosen row of a table is `bg-panel`; a chosen card or list
row is `bg-panel` with `border-primary` (a border, no ring). While something is chosen, the
**selection bar** (`SelectionBar`) names how many and what an action will leave out, then
"Auswahl aufheben" (`ghost`) and the actions (`outline`, the primary `default` last), all `sm`.
It has the card look through `cardVariants`: on desktop it stands above the list in `bg-panel`
and sticks below the header (`top-20`); on the phone it sticks to the bottom of the screen
(`bg-card`, a line above), the hint as a line of its own and its two actions sharing the width.
One item is still decided in its dialog, opened from its title: the actions stay out of the
row. The open identifiers are a `ui/table` on a desktop; on a phone they are rows, and the
whole row opens the identifier (as the rows of the master data do) or, while some are chosen,
chooses it.

The documents list chooses in a **selection mode** (Tobi 28.10.2026): outside it the cards and
rows carry no box and no bar shows. A button with `ListChecks` (`outline`, "Auswählen",
`aria-pressed`) beside the sort turns it on and off; on the phone it stands in the row of
filters. In the mode a card or row is the label of its box instead of a link: the box starts
the card's head (the first page stays clear) or the row, a tap anywhere chooses it, and a
chosen one has the chosen look above. The bar (`SelectionBar`) shows from the start of the
mode, with no hit too: an X that ends it, "Auswählen" (`outline`, a menu: "Diese Seite
auswählen", "Alle N Treffer auswählen" where there are more than the page, "Keine auswählen",
and after a separator "Auswahlmodus beenden"), how many are chosen, a hint while none is, and
the actions, disabled while none is chosen: "Tags", "Kontakt", "Typ" and "Mehr" (a menu: Thema,
Space, Bestätigen, Neu verarbeiten, and after a separator Löschen in `destructive`). On the
phone the bar sits at the bottom: X, the count and "Auswählen" above, the hint as a line of its
own, the four actions sharing the width below. With all hits chosen the choice is the search
and filters, not ids, and the bar says so (with words, how far the search reaches). Each action
but "Bestätigen" opens a `FormDialog` (deleting: a `ConfirmDialog` naming the count). The
action runs in the background, owned by the page (`BulkRun`), not by the bar: the bar shows a
`Progress` with "412 von 1.234 …" in place of its actions; at the end a toast says what it did,
and where documents were skipped, "Details" opens them with their reasons. The mode stays after
an action and when the filters change (the choice is let go) until the person ends it.

**Pages** (Tobi, 28.10.2026): the documents list pages as a table does, in its grid and its list,
with `Pagination` and the page in the link (`?page=`); it offers 25, 50 and 100 to a page (50
at first), remembered as a table's size is. A reconnect of the event stream loads the page
shown again as it stands; only a change of words, filters, sort or scope goes back to the first
page.

**A recommendation** (the open identifiers, Tobi 28.10.2026): where the data tell what to do with
an item, its row says so in a column of its own as a `Badge` without an icon (its words tell),
`green` for "Übernehmen empfohlen", `muted` for "Verwerfen empfohlen", "–" where nothing is
recommended (said in words to a screen reader); why stands in its tooltip (its trigger takes
the focus), for a screen reader inside the badge, and in the item's dialog beside the badge. A
value of the `Segmented` above the list ("Empfohlen", with its count) shows the recommended
alone. Taking every recommendation at once is an `outline` button beside the filters with the
count ("Empfohlene übernehmen (9)"), over all pages, after a `ConfirmDialog` that names the
count and why; only for what keeps its way back (confirming), never for rejecting.

**A folded group** (`FoldedGroup`; the numbers of third parties among the facts, Tobi
28.10.2026): rows that belong to a card but rarely matter fold away at its end. Above them a
line (`border-t`), then one `button` the width of the card, at least 44 px: a `ChevronRight`
(`muted-foreground`) turned down when open (`motion-safe`), the count in words (`text-sm
font-medium`) and below it what they are (`text-xs text-muted-foreground`); `aria-expanded` and
`aria-controls`. Closed at first; opened, it stays open while the page shows the same thing. The
rows inside look as elsewhere in the card, indented to the text of the button (`pl-6`). A whole
card that folds is `FilterSection`.

### Tables

`ui/table` only. The head is `text-xs font-medium text-muted-foreground`. Numbers align right with
`tabular-nums`. A count of mistakes is `text-lane-red-foreground` above nought, `muted` at nought;
a count of what went right may name its whole (`29 von 29`, the whole in `muted`) and has no
colour of its own: lane colours mean state. On the phone a table keeps to the columns that fit;
where it is wider, it scrolls inside its card, never the page. A list a person reads item by
item is a list of rows, not a table. Pagination is `Pagination`, 50 to a page unless the table
offers other sizes in a small menu beside the count (`outline`, `sm`): the jobs and the
deliveries of a webhook 25, 50 and 100, 25 at first; the choice is remembered per table in the
browser (`page-size.ts`) and holds wherever that table shows. Above such a table, a `Segmented`
with counts picks what it shows and a `Select` narrows it to a kind (the jobs by state and kind,
the deliveries by outcome and event). The documents list pages the same way (see [Lists](#lists)).

### Dialogs, sheets, editors

| Need                                                         | Component                                   | Desktop                          | Phone                                                                                                                 |
| ------------------------------------------------------------ | ------------------------------------------- | -------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Ask before a destructive action                              | `ConfirmDialog` (alert dialog)              | centred, `size="md"`             | centred with gutter                                                                                                   |
| A short form (space, token, code, move, reprocess, new user) | `FormDialog`                                | centred, `size` `sm`/`md`/`lg`   | full screen with the editor bar                                                                                       |
| An editor of master data, lenses                             | `EditorShell`                               | dialog with sticky head and foot | full screen with the editor bar                                                                                       |
| A secret shown once                                          | `SecretDialog`                              | centred, `size="md"`             | centred with gutter                                                                                                   |
| A choice from many (tags, facets; contact, type, topic)      | popover / `TagPickerDialog`, `SearchSelect` | popover or dialog                | sheet from the bottom (`PhoneSheet`; `SearchSelect`: see [Fields](#fields))                                           |
| Filters                                                      | sidebar                                     | sidebar                          | sheet from the bottom, title and close fixed on top, "Zurücksetzen" and "Ergebnisse anzeigen (N)" fixed at the bottom |
| A document's pages without leaving the place                 | `Beam`                                      | sheet from the right, 640 px     | full screen                                                                                                           |

- **Widths** come from the `size` prop (`sm` 384 px, `md` 512 px, `lg` 672 px, `xl` 768 px).
  A `class="max-w-*"` on dialog content is not used.
- **Phone editor bar:** "Abbrechen" · title · "Speichern", fixed on top. The body scrolls. The
  action is a short verb there: a longer label of the desktop ("Ins Profil von Anna") becomes its
  verb ("Übernehmen"), and the body names the rest (Tobi 29.10.2026).
- **Sheet from the bottom:** `PhoneSheet`, on `ui/sheet` with `side="bottom"`: a grab handle,
  the title and its close button (an X, "Fertig") fixed on top, 85 % of the screen high;
  nothing takes the focus when it opens. The pickers (`SearchSelect`, `TagPickerDialog`) use
  it; its classes are written nowhere else.
- **A second way out:** `FormDialog` takes `alternative`, an action that finishes the dialog
  as well, without asking (rejecting an open identifier beside taking it over): `outline` at the
  start of the footer; on the phone below the fields.
- **Delete in an editor:** a `FormDialog` or `EditorShell` with `ondelete` shows "Löschen" at the
  start of its footer, apart from the two actions, and asks with `ConfirmDialog`.
- **Dialog footer:** see [Patterns](#footers).
- **Beam:** the one sheet from the right with content (see [Beam](#beam)).
- A dialog title names its object: "„Stromrechnung Oktober“ löschen", never a bare "Löschen".

### Beam

The Beam shows a document's pages without leaving the place: wherever Lekto names a document or
claims something from one, a person sees it with one tap. `Beam.svelte`, mounted once in the
app shell, on `ui/sheet` with `side="right"`: 640 px on a desktop, the whole screen on a phone,
modal, over a dialog too.

- **It only shows:** the eyebrow "Beam", the title, a line with contact · type · date; then,
  with more than one document, the arrows and "Dokument 2 von 24" (keys ← →); the pages in the
  document view's `PageViewer` (one page to a row at the start; buttons, Ctrl/⌘ with the wheel,
  pinch, double click, + − 0); at the bottom "Dokument öffnen", on a phone across the width.
  Editing happens in the document view.
- **Opening it:** "Ansehen" (`ViewButton`, icon `scan-eye`; never "Beamen"): on a card's first
  page as glass with its name, always shown; at the end of a row or beside a title as an icon.
  The title keeps opening the document. From a list, the Beam pages through the list's page.
  Where a dialog or a card lists documents as evidence (Fundstellen, a relation, similar
  documents), the title itself opens the Beam, the eye before it, cut to one line; into the
  document from the Beam. A relation shows both documents, the newer first, the number they
  share marked in each.
- **State:** the history entry's (`beam.svelte.ts`): ids only. The back button closes it, a
  reload brings it back, paging replaces the entry. A document that is gone closes it with a
  toast.
- **"Dokument öffnen"** jumps there with the way back to here (see
  [Navigation between list and detail](#navigation-between-list-and-detail)).
- **Places:** where Lekto claims a value from a document, the Beam marks each place the pages
  show it, the one the fact was read at with a halo and its kind ("IBAN"), and scrolls there;
  it pages through the places ("Fundstelle 2 von 5"). The places come from the endpoint that
  names the fact (`occurrences`), never from a search of its own. From the inbox ("Ansehen" in a row)
  it marks the quotes of the fields that keep each document there, each with the field's name,
  the first with a halo: why it is yellow, on the page.
- **Over a dialog:** a dialog that opens the Beam keeps its state in the history entry too, so
  the back button closes the Beam, then the dialog, and the way back from a document returns to
  both. From 1280 px the dialog moves aside while the Beam is open (`app.css`), so both stand
  side by side; narrower, the Beam lies over it.

### Alerts

`Alert` (`ui/alert`) for notes inside a page, after GitHub and Docusaurus:

| Variant                  | Use                                       |
| ------------------------ | ----------------------------------------- |
| `default`                | A plain note without tone                 |
| `note` (blue)            | Information to know                       |
| `tip` (blue, light bulb) | A recommendation (e.g. read with the VLM) |
| `warning` (yellow)       | Something to check before going on        |
| `caution` (red)          | A risk or a failure                       |

Toasts (`svelte-sonner`) confirm an action that has finished ("Gespeichert", "3 Dokumente
eingereiht") or report an error of an action. **A toast never replaces a load error on the page.**

### Help and tooltips

- **Help of a field or section:** `InfoTip` or `HintLabel`, an info button beside the label that
  opens the text. The visible text stays what one needs to read the view. Help text holds at most
  about 200 characters. Longer explanations belong in the documentation.
- **Tooltip** (`ui/tooltip`): the name of an icon button (through `IconButton`), the names of the
  options of `Segmented`, the inbox mark of a card. A native `title=` attribute is used only for
  text that is cut off (a truncated name, "+3" for the rest of the tags) and for the names of
  options in pickers (swatches, icons, months, tag paths), never on buttons.
- Information is never available only through hover. On the phone a tooltip's content must also be
  reachable another way (label, sheet, detail).

### Document card

The grid card "contact on top":

1. **Head:** the contact's avatar (logo or initials) and name. Right: the inbox mark as a small
   badge (icon, tooltip "Im Posteingang", link to the document in the inbox), when it stands there.
2. **First page:** the page image (`DocumentThumb`, white paper in both modes). The page count sits
   bottom right as a glass mark (`.mark-glass`). Nothing else covers the page.
3. **Body:** the title (bold, two lines, hyphenated), type with icon and date, then topic, tags
   and groups as chips in one line (three fit) with "+n" for the rest. Lens card fields
   (`CardFields`) follow below a line.

`DocumentRow` (list) and `InboxRow` (inbox) show the same parts in a row: thumbnail, title, contact
and type, tags, state.

### Overview tiles

The overview (`/`) shows what waits for someone as tiles in a grid (one column on the phone, two
from `sm`, three from `lg` when there are three). A tile is a `Card` (`md`): an icon and its
`Card.Title` (the place's name), the big number (`text-figure`, `tabular-nums`) with what it
counts, badges in their tones (icon and word for a lane), one `text-meta` line of detail, and at
its foot the way there, a `brand` link with an arrow ("Zum Posteingang"). Badges on a tile are
not links. While a tile loads it shows a `Skeleton` in the place of the number.

### Lenses

`Lenses` lists the user's lenses as links, "Alle Dokumente" first: beside the documents' filters
a card under the eyebrow "LENSES" (`list`), on the phone and with the filters collapsed a row
of chips (`chips`). On a desktop a count in `text-xs text-muted-foreground tabular-nums` stands
beside each name, "Alle Dokumente" counted too: counted with the list, again on events and on a
switch of the scope (Tobi, 28.10.2026). The chips show none.

## States

Every view that loads has these four states. Each looks the same everywhere:

| State     | Component                                                              | Notes                                                                                            |
| --------- | ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Loading   | `Skeleton` in the shape of the content, or `Loading` (`role="status"`) | The page header stays                                                                            |
| Empty     | `EmptyNote` (dashed box, `action` for the way)                         | Says what would be here and how it gets here; a link or button to that action where there is one |
| Error     | `LoadProblem` (`role="alert"`, "Erneut versuchen")                     | On the page, not as a toast. A detail page keeps its header and back link                        |
| Not found | `LoadProblem` with the way back                                        | Never a dead end                                                                                 |

## Patterns

### Footers

The same order everywhere, dialogs and page forms alike: right-aligned, **"Abbrechen"** (`ghost`)
then **the primary action** (`default`). A destructive confirmation puts the destructive button in
the primary place. While the action runs, both buttons are held (`ConfirmFooter`, `AsyncForm`). On
the phone a full-screen editor carries the same two actions in its top bar.

### Saving and leaving

- Forms save with "Speichern" or a verb that names the result ("Speichern und Probelauf",
  "Anlegen"). An action that takes effect at once (switch, chip) needs no save.
- **Unsaved changes are guarded.** A form with changes asks before the user leaves it: by a link,
  a tab, the back button, closing the dialog or closing the browser (`beforeNavigate`,
  `beforeunload`). The question is a `ConfirmDialog` with "Verwerfen" and "Weiter bearbeiten":
  `UnsavedGuard`, or `AsyncForm` with `onchanged`.
- Panes of the document page keep their state while hidden.

### Destructive actions

Delete, remove, revoke, leave and hand over **always** ask with `ConfirmDialog`. This includes
removing a space member and a relation. The dialog names the object and the consequence.
Destructive actions are in editors and on detail pages, not in list rows.

### Navigation between list and detail

- A list's state (lens, filters, sort, layout) lives in its URL, its words in the history entry
  (see "No plain data in addresses"). A detail page reached from a list carries that URL and
  entry back (`from`), and its `BackLink` returns there. The inbox's previous/next works the same
  way.
- Detail pages of the same kind offer the same actions in the same place: header actions (edit,
  primary action). A single destructive action stands there as an `IconButton` (rule, webhook);
  where there are more actions, a "…" menu holds the rest (delete last, in `destructive`).
- `return-to.svelte.ts` keeps the list's URL and words for the way back.
- **After a jump** (the Beam's "Dokument öffnen", later a dialog's link): the new history entry
  names where it came from (`way-back.ts`, `page.state.from`). The document's `BackLink` then
  reads "Zurück zu {place}" and goes back in the history, one step, as the back button does: to
  the place as it was, its dialog and Beam open. Leaving a document (deleted, handed over) takes
  the same way.

### No plain data in addresses

What a person types or what comes from a document (the words of a search, an IBAN, an invoice
number) never stands in a URL: not in the address bar, not in a request to the API. URLs end up
in the browser history, bookmarks, the `Referer` and proxy logs.

- In a URL: ids, choices (a tab, a sort, a lane), and references. A fact's value is its
  reference (`ref`, from `POST /identifiers/refs` or an answer that names the value):
  `fact=iban:<ref>:`. Its label asks the API for the value (`fact-refs.svelte.ts`).
- State that carries such data lives in the history entry: `goto(url, { state, persistState:
true })`, read from `page.state` (`lib/words.ts` for the words of the documents). The back
  button and F5 bring it back; a plain link opens without it.
- Words go to the API in a body (`POST /documents/search`); never put them into a query.
- Not in `localStorage` either: that is per browser and outlives the tab.

### Steady layout

What a person did not touch stays where it is: choosing something, or going to another page,
moves nothing beside it.

- **A label that turns bolder when chosen** (a link of the menu, a tab, a switch, a chip that
  toggles, a lens chip) keeps its width: `SteadyText` holds the room of its bolder weight (for
  markup, the `steadyText` attachment). Never change a label's weight without it where something
  stands beside it, and add nothing when chosen (a check): an edge stays 1 px in both states.
- **The head of a page** is as high as a button, with actions beside the title or without
  (`PageHeader`, and the documents' own head), so that the title and what follows stand at the
  same height on every page.
- **The room of a scroll bar** stays reserved (`scrollbar-gutter: stable` on `html`): a page
  longer than the window, or a dialog that locks it, does not shift the page sideways where the
  system shows scroll bars (Windows, a Mac with a mouse).
- A strip of tabs that scrolls on a phone brings the chosen tab into view; that is no move.

### Motion

Only `motion-safe`: the sliding pill of `Segmented`, the underline of `TabBar`, opening sheets and
dialogs. Nothing moves on first show. Nothing grows over its neighbours on hover.

## Touch targets

- **Phone (below `sm`):** every control is at least 44 × 44 px. A smaller visual element (the ✕ of
  a chip) gets an invisible larger hit area (`after:absolute after:-inset-*`). Neighbouring targets
  do not overlap.
- **Desktop:** at least 32 px for controls in rows and cards, 40 px elsewhere. No target is smaller
  than 24 × 24 px.
- The components implement this (`Button`, `IconButton`, `Chip`, `Segmented`, `TabBar`, `Select`,
  `Switch`, `ChoiceBox`, `InfoTip`, `BackLink`, `InboxMark`). Pages do not add sizes by hand.

## Accessibility baseline

What the components already guarantee and new code keeps:

- every control has a name; icon-only buttons through `IconButton`'s label, which includes the
  object's name in lists ("Test an „Home Assistant“ senden");
- every input has a label; errors are tied to their field;
- headings in order; one `<h1>` per page;
- a visible focus everywhere (`:focus-visible` in `app.css`); a skip link to the content;
- state by icon and word, not colour alone;
- `aria-current` in navigation and tabs, `aria-pressed` on toggles.

## Texts

Every text a user reads is in `messages/en.json` and `messages/de.json` (`no-raw-text.test.ts`).

### German

- **Form of address: the polite "Du" with a capital D**: Du, Dich, Dir, Dein, Deine, Euch, Euer.
  Never "Sie", never a lowercase "du".
- Short sentences, active voice, no jargon a user does not know. Technical reasons from the API
  are translated (`x-reasons`).
- Buttons are verbs or verb phrases ("Als gesehen markieren", not "Gesehen").

### Words

| Concept                              | German              | English              |
| ------------------------------------ | ------------------- | -------------------- |
| Save a form                          | Speichern           | Save                 |
| Leave without saving                 | Abbrechen           | Cancel               |
| Discard unsaved changes              | Verwerfen           | Discard              |
| Enabled / disabled (rules, webhooks) | Aktiv / Pausiert    | Active / Paused      |
| Enabled / disabled (users)           | Aktiv / Deaktiviert | Active / Deactivated |
| Create                               | Anlegen             | Create               |
| Delete                               | Löschen             | Delete               |

### Glossary

Product terms stay as they are in both languages: **Lens** (plural Lenses), **Space**, **Stream**.
Other terms are translated: Posteingang (Inbox), Dokumente (Documents), Erwartet (Expected),
Regeln (Rules), Stammdaten (Master data), Nutzer (Users), Kontakt, Dokumenttyp, Tag, Thema
(Topic), Gruppe (Group), Feld (Field), Fakt (Fact), Bezug (Relation), Lane names Erledigt, Prüfen,
Eingreifen, In Verarbeitung.

### Formats

Dates and numbers follow the UI language (`Intl`): `26.10.2026`, `123,45 €` in German. Durations
are short and do not wrap ("4,2s", "1m 3s").

## Exceptions

Allowed outside the token rules, each for a stated reason:

| Where                                                                   | What                                   | Why                                                                  |
| ----------------------------------------------------------------------- | -------------------------------------- | -------------------------------------------------------------------- |
| `PageViewer`, `DocumentThumb`, `CodeThumb`, `ContactAvatar`, `TotpCard` | `bg-white`                             | Paper, logos and the QR code are drawn for white                     |
| Overlays of `ui/dialog`, `ui/alert-dialog`, `ui/sheet`                  | `bg-black/*`                           | The dimmed page behind a dialog, as shadcn draws it                  |
| The sign-in page                                                        | an arbitrary font size                 | The wordmark scales with its font size                               |
| `DocumentFiles`                                                         | `hsl()` from data                      | The fingerprint colour comes from the file's hash                    |
| `PageViewer`, `ProcessingBand`, charts                                  | `style=` with computed sizes           | Sizes come from data (zoom, durations, bars)                         |
| `lib/templates/codemirror.ts`                                           | its own theme                          | The editor sits in a shadow root that the page's styles do not reach |
| `.lc-tooltip-*` in `app.css`                                            | LayerChart override                    | The library's tooltip ground is otherwise transparent                |
| `ui/*`                                                                  | shadcn internals (`data-[…]` variants) | Primitives; their look follows this document                         |

A new exception needs a row here and its entry in `tests/design-system.test.ts` (`EXCEPTIONS`).

## Enforcement

- **Guard tests** (Vitest) fail `pnpm test` when a rule is broken:
  - `tests/design-system.test.ts`: font sizes, radii, shadows and colours from the tokens only
    (no arbitrary values, no Tailwind palette) outside the exceptions; `<h1>` only in
    `PageTitle`; `<table>` only in `ui/table`; no `title=` on `Button`, `IconButton` or a menu
    trigger; no `max-w-*` on dialog content; icon buttons only through `IconButton`;
  - `tests/messages-tone.test.ts`: German texts without "Sie" and without a lowercase "du";
  - `tests/no-raw-text.test.ts`: no raw text in markup; `tests/no-raw-choice.test.ts`: no raw
    checkbox or radio.

  Their lists of exceptions may only shrink.

- **Layout spec** (Playwright, `tests/e2e/layout.spec.ts`): every area at 390, 1024 and 1440 px.
  No horizontal overflow, 44 px targets on the phone and 24 px wider (a larger invisible hit area
  counts), no console error.
- **Living style guide:** `/dev/components` (development builds) shows every component in every
  variant and size, in light and dark. A new component or variant is added there first.
- **Review:** every pull request that touches `web/` confirms it follows this document (the
  checklist of `.github/pull_request_template.md`); a deviation needs a change of this document
  in the same pull request.
