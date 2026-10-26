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

## Migration status

#167 brings the code to this document step by step. Until a step has landed, the code may still
show the old way. New code follows this document, not the old way.

| Step of #167                 | Rules of this document it makes true                                                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 2 Tokens and page frame      | [Typography](#typography), [Radius](#radius-borders-shadows), [Page frame](#page-frame), [Cards](#cards)                                                     |
| 3 Widgets                    | [Badges](#badges), [Chips](#chips), [Tabs and switches](#tabs-and-switches), [Tables](#tables), [Fields](#fields), [Checkboxes](#checkboxes-radios-switches) |
| 4 Tooltips and touch targets | [Icon buttons](#buttons), [Tooltips](#help-and-tooltips), [Touch targets](#touch-targets)                                                                    |
| 5 Fixes                      | [States](#states), [Dialogs](#dialogs-sheets-editors) (widths)                                                                                               |
| 6 Flows and layout           | [Patterns](#patterns), [Navigation](#navigation), [Document card](#document-card), [Date field](#fields)                                                     |
| 7 Texts                      | [Texts](#texts)                                                                                                                                              |
| 8 Guardrails                 | [Enforcement](#enforcement)                                                                                                                                  |

When a step lands, its row is removed. When the table is empty, this section goes.

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
| `beta`, `beta-foreground`                                                 | The "Beta" pill only                                                                                                                 |
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

| Step (class)      | Size                     | Use                                                  |
| ----------------- | ------------------------ | ---------------------------------------------------- |
| `text-title`      | 1.75rem, semibold, tight | The page title (`<h1>`), only through `PageHeader`   |
| `text-figure`     | 1.625rem, semibold       | A big number on a stat card                          |
| `text-section`    | 1.125rem, semibold       | A section of a page (`<h2>`), through `SectionTitle` |
| `text-base`       | 1rem                     | Reading text, dialog titles                          |
| `text-card-title` | 0.9375rem, semibold      | The heading of a card or pane (`<h2>`/`<h3>`)        |
| `text-sm`         | 0.875rem                 | Default UI text: rows, fields, buttons               |
| `text-meta`       | 0.8125rem                | Secondary lines, dense panels (system, processing)   |
| `text-xs`         | 0.75rem                  | Captions, badges, the eyebrow                        |
| `text-micro`      | 0.6875rem                | Marks on images (page count), counters in pills      |

- **Eyebrow** (small uppercase label above a group, e.g. "LENSES", "ZEITRAUM"): the `Eyebrow`
  component (`text-xs font-medium uppercase tracking-wide text-muted-foreground`).
- **Headings in order:** one `<h1>` per page (`PageHeader`), then `<h2>`, then `<h3>`. Do not
  skip a level for the sake of looks.
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

All radii come from `--radius`. `rounded-3xl`, `rounded-4xl` and arbitrary radii are not used.

**Borders:** one hairline, `border` in `border-border`. Cards use `border`, not `ring`. Dashed
borders mean "empty" or "add": `EmptyNote` and the dashed "+ …" chip.

**Shadows:** cards have none. Popovers, menus and dialogs use the component's shadow. Marks on a
page image use `.mark-glass`. No other shadows.

**Dividers:** `ui/separator`, not hand-built `h-px`/`w-px` elements.

## Spacing and layout

- **Page:** `flex flex-col gap-6` from the header down. Sections inside a page use `gap-3` between
  their title and content.
- **Card padding:** `Card` sizes only. `sm` = `p-3.5` (dense panels: facts, relations), `md` =
  `p-5` (default), `lg` = `px-6 py-5`. Hand-built paddings are not used.
- **List rows:** `px-4 py-3`, at least 56 px tall.
- **Breakpoints:** Tailwind defaults: `sm` 640, `md` 768, `lg` 1024, `xl` 1280, `2xl` 1536 px.

### Page frame

`AppShell` holds every signed-in page. Each page starts with `PageHeader`:

- **Back link** (optional, detail pages): `BackLink`, above the title. It leads to the list the
  page came from, with that list's state: lens, filters, search and sort.
- **Title**: `<h1>` in `text-title`, optionally followed by a count or a badge (lane, Beta).
- **Subtitle** (optional): one line in `text-sm text-muted-foreground` under the title.
- **Actions**: right of the title, at its height. The primary action of the page is last
  (rightmost). On the phone, a page action may become an icon button. It keeps its label as
  tooltip and `aria-label`.

The header shows **while loading and after an error**. The title shows a skeleton or the generic
name of the page ("Regel"), never "Edit " with an empty name.

### Page widths

| Width    | Max     | Pages                                       |
| -------- | ------- | ------------------------------------------- |
| Wide     | 1600 px | Documents (`/documents`), the document page |
| Standard | 1040 px | Every other page, settings included         |

Content inside a standard page may be narrower for reading (a form column), never the page itself.
From desktop width the document page fills the window and scrolls only inside its panes. On the
phone the page scrolls.

## Navigation

- **Menu:** two groups divided by a line. _Work_: Posteingang · Dokumente · Erwartet · Spaces.
  _Set-up and operation_: Regeln · Webhooks · System · Stammdaten · Nutzer. The rights stay
  (master data and users for admins only).
- **From `lg` (1024 px):** the menu stands in the header. If it does not fit, the second group goes
  behind "Mehr".
- **Below `lg`:** a sheet from the right. Its button is the rightmost item of the header (thumb
  corner).
- **Header items:** logo (favicon icon before the wordmark "lekto"), menu, search (the field where
  the header has room, `searchPlaces`: from `2xl`, for admins from 1720 px; otherwise the
  magnifier), user menu (avatar).
- **User menu:** name and role, the admin switch "Alle Nutzer einbeziehen", language and appearance
  (as `Segmented`), settings, API documentation, sign out. On the phone (below `sm`) the sheet
  holds all of it: the header shows only logo, magnifier and menu button.
- **Inbox counter:** a badge on the menu entry, coloured by the worst lane it holds.
- **Beta:** a small `BetaPill`, raised at the menu entry, and a larger one beside the page title
  that opens its note as an info tip.

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

On the phone every button is at least 44 px tall (see [Touch targets](#touch-targets)). The
component handles this. Pages do not add `h-11` by hand.

**Icon buttons:** `IconButton` only. It takes a `label` (its tooltip and `aria-label`), a variant
and a size (`default` 40 px, `sm` 32 px). Icon buttons are rectangles like every button. There is
no round "+". Plain `<button>`s are allowed only for whole-row targets and chips, never as
look-alikes of `Button`.

**Menus:** several actions of one object go into a menu: "…" for the rest, "Herunterladen" for
formats, the sort as `SortMenu`.

**Pen:** in every list whose entries have an editor, `EditButton` is the last column behind a
divider.

### Fields

- **`Input`**: `rounded-xl`, 44 px tall, `bg-card`, `border-input`. `Textarea`, `Select`,
  `SearchSelect` and `SearchField` share its look through `fieldVariants`.
- **Label:** `Label`, or `HintLabel` when the field has help (info button beside the label, see
  [Help](#help-and-tooltips)). Every field has a label.
- **Errors:** `Field.Error` under the field, tied to it with `aria-describedby`.
- **`Select`**: a short, fixed list. On desktop a list in the style of the other pickers, on the
  phone the system's native picker.
- **`SearchSelect`**: a long list (contact, document type, topic). Admins can create from the
  search (`CreateOffer`).
- **`SearchField`**: every search input, in pickers, lists and pages alike. The header search and
  the document search are `SearchField`s inside a form.
- **Dates:** `DateField` (bits-ui), in the UI language. Not `<input type="date">`, which follows
  the browser language. `PeriodInput` handles periods.
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

`Chip` is the one chip: a pill, `h-8` (44 px target on the phone), icon and name, optionally
removable (✕) or toggleable (`aria-pressed`). Its variants:

| Variant   | Use                                                              |
| --------- | ---------------------------------------------------------------- |
| `filled`  | Tags and topics, in their colour (`chipLook()`)                  |
| `outline` | Groups (contact and type groups)                                 |
| `neutral` | Free values (spellings), active filters, search words            |
| `add`     | The dashed "+ Gruppe" / "+ Thema" / "+ Name" that opens a picker |

All chips are pills, topics included. The field a chip stands in names its kind. A selected toggle
chip uses `bg-panel text-brand` with a check icon. `TagChip`, `TagChips`, `GroupChips`,
`FacetChips` and `ChipInput` render `Chip`.

### Badges

`Badge` (`ui/badge`) shows a state or a short fact. It is never a button.

| Tone                                | Use                                                                                        |
| ----------------------------------- | ------------------------------------------------------------------------------------------ |
| `green`, `yellow`, `red`, `running` | Lane and state ("Erledigt", "Prüfen", "Eingreifen", "In Verarbeitung"; "Aktiv"); with icon |
| `note`                              | Neutral information with meaning ("Persönlich", scope)                                     |
| `neutral`                           | Plain facts ("1 S.", counts, "Pausiert")                                                   |
| `warning`                           | A caveat that matters: "Unsigniert" (yellow tone)                                          |
| `beta`                              | Through `BetaPill` only                                                                    |

Heights: `sm` 20 px (in rows, `text-xs`), `md` 24 px (in headers). `LaneBadge` is `Badge` with
the lane tone. Hand-built pills are not used.

### Tabs and switches

Two components that **look different on purpose**:

- **`TabBar`**: the tabs of a page (inbox lanes, document, master data, system). Links that change
  the URL. **Underline tabs:** text in `muted-foreground`, the current tab in `foreground` with a
  2 px `brand` underline. A bottom border runs across the bar. It scrolls sideways on the phone
  with a fade at the cut edge. Counts and dots sit beside the label.
- **`Segmented`**: a choice of how to show something (pages, grid/list/stream, text/pages,
  form/facts, period quick picks, language, appearance). A grey bar with the choice on a light
  pill that slides over (`motion-safe`, not on first show). Sizes: `md` 40 px, `sm` 32 px; 44 px on
  the phone. With icons only (`names="hidden"`) every option has a label for its tooltip.

No other tab or segmented look exists. `AutomationTab` and `PeriodFacet` use `Segmented`.

### Cards

`Card` (`ui/card`): `rounded-2xl border bg-card`, sizes `sm`, `md`, `lg` (see
[Spacing](#spacing-and-layout)). `Card.Title` renders a heading (`<h2>` by default, `level` to
change it) in `text-card-title`. `Card.Description` is `text-sm text-muted-foreground`. Hand-built
`div`s with border and radius are not used.

### Lists

Lists of items (rules, webhooks, spaces, users, master data) are rows in one card, or cards in a
column. Each row has:

1. **Leading** (optional): avatar, icon or thumbnail.
2. **Title**: a link to the detail page, or the opener of the editor where there is no detail page.
3. **Secondary line**: `text-meta text-muted-foreground`, with badges at the title.
4. **Trailing**: at most the `Switch` (where there is one) and the `EditButton`. Counts may stand
   before them as links.

**Delete, test, rotate secret, log and other actions live on the detail page or in the editor,**
not in the row. On the phone the whole row opens the editor or the detail page. It shows the
secondary line and a chevron, no buttons.

### Tables

`ui/table` only. The head is `text-xs font-medium text-muted-foreground`. Numbers align right with
`tabular-nums`. On the phone a table with more than three columns becomes rows (a stacked layout).
It does not scroll sideways. Pagination is `Pagination` (50 per page).

### Dialogs, sheets, editors

| Need                                                         | Component                      | Desktop                          | Phone                                                                                                                 |
| ------------------------------------------------------------ | ------------------------------ | -------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| Ask before a destructive action                              | `ConfirmDialog` (alert dialog) | centred, `size="sm"`             | centred with gutter                                                                                                   |
| A short form (space, token, code, move, reprocess, new user) | `FormDialog`                   | centred, `size` `sm`/`md`/`lg`   | full screen with the editor bar                                                                                       |
| An editor of master data, lenses                             | `EditorShell`                  | dialog with sticky head and foot | full screen with the editor bar                                                                                       |
| A secret shown once                                          | `SecretDialog`                 | centred, `size="md"`             | centred with gutter                                                                                                   |
| A choice from many (tags, facets)                            | popover / `TagPickerDialog`    | popover or dialog                | sheet from the bottom                                                                                                 |
| Filters                                                      | sidebar                        | sidebar                          | sheet from the bottom, title and close fixed on top, "Zurücksetzen" and "Ergebnisse anzeigen (N)" fixed at the bottom |

- **Widths** come from the `size` prop (`sm` 384 px, `md` 512 px, `lg` 640 px, `xl` 768 px).
  A `class="max-w-*"` on dialog content is not used.
- **Phone editor bar:** "Abbrechen" · title · "Speichern", fixed on top. The body scrolls.
- **Dialog footer:** see [Patterns](#footers).
- A dialog title names its object: "„Stromrechnung Oktober“ löschen", never a bare "Löschen".

### Alerts

`Alert` (`ui/alert`) for notes inside a page, after GitHub and Docusaurus:

| Variant                  | Use                                       |
| ------------------------ | ----------------------------------------- |
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
- **Tooltip** (`ui/tooltip`): the name of an icon button (through `IconButton`), the full text of
  something cut off, the path of a tag. A native `title=` attribute is used only for cut-off text,
  never on buttons.
- Information is never available only through hover. On the phone a tooltip's content must also be
  reachable another way (label, sheet, detail).

### Document card

The grid card "contact on top":

1. **Head:** the contact's avatar (logo or initials) and name. Right: the inbox mark as a small
   badge (icon, tooltip "Im Posteingang", link to the document in the inbox), when it stands there.
2. **First page:** the page image (`DocumentThumb`, white paper in both modes). The page count sits
   bottom right as a glass mark (`.mark-glass`). Nothing else covers the page.
3. **Body:** the title (bold, two lines, hyphenated), type with icon and date, then the tags as
   chips in one line with "+n" for the rest. Lens card fields (`CardFields`) follow.

`DocumentRow` (list) and `InboxRow` (inbox) show the same parts in a row: thumbnail, title, contact
and type, tags, state.

## States

Every view that loads has these four states. Each looks the same everywhere:

| State     | Component                                                                | Notes                                                                                            |
| --------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| Loading   | `Skeleton` in the shape of the content, or "Lädt …" with `role="status"` | The page header stays                                                                            |
| Empty     | `EmptyNote` (dashed box)                                                 | Says what would be here and how it gets here; a link or button to that action where there is one |
| Error     | `LoadProblem` (`role="alert"`, "Erneut versuchen")                       | On the page, not as a toast. A detail page keeps its header and back link                        |
| Not found | `LoadProblem` with the way back                                          | Never a dead end                                                                                 |

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
  `beforeunload`). The question is a `ConfirmDialog` with "Verwerfen" and "Weiter bearbeiten".
- Panes of the document page keep their state while hidden.

### Destructive actions

Delete, remove, revoke, leave and hand over **always** ask with `ConfirmDialog`. This includes
removing a space member and a relation. The dialog names the object and the consequence.
Destructive actions are in editors and on detail pages, not in list rows.

### Navigation between list and detail

- A list's state (lens, filters, words, sort, layout) lives in its URL. A detail page reached from
  a list carries that URL back (`from`), and its `BackLink` returns there. The inbox's
  previous/next works the same way.
- Detail pages of the same kind offer the same actions in the same place: header actions (edit,
  primary action), a "…" menu for the rest (delete last, in `destructive`).

### Motion

Only `motion-safe`: the sliding pill of `Segmented`, the underline of `TabBar`, opening sheets and
dialogs. Nothing moves on first show. Nothing grows over its neighbours on hover.

## Touch targets

- **Phone (below `sm`):** every control is at least 44 × 44 px. A smaller visual element (the ✕ of
  a chip) gets an invisible larger hit area (`after:absolute after:-inset-*`). Neighbouring targets
  do not overlap.
- **Desktop:** at least 32 px for controls in rows and cards, 40 px elsewhere. No target is smaller
  than 24 × 24 px.
- The components implement this (`Button`, `IconButton`, `Chip`, `Segmented`, `TabBar`). Pages do
  not add sizes by hand.

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
| `DocumentFiles`                                                         | `hsl()` from data                      | The fingerprint colour comes from the file's hash                    |
| `PageViewer`, `ProcessingBand`, charts                                  | `style=` with computed sizes           | Sizes come from data (zoom, durations, bars)                         |
| `lib/templates/codemirror.ts`                                           | its own theme                          | The editor sits in a shadow root that the page's styles do not reach |
| `.lc-tooltip-*` in `app.css`                                            | LayerChart override                    | The library's tooltip ground is otherwise transparent                |
| `ui/*`                                                                  | shadcn internals (`data-[…]` variants) | Primitives; their look follows this document                         |

A new exception needs a row here.

## Enforcement

- **Guard tests** (Vitest, after the pattern of `tests/no-raw-choice.test.ts`) fail `pnpm test`
  when a rule is broken:
  - no arbitrary font sizes, radii, shadows or Tailwind palette colours outside the exceptions;
  - no raw `<table>`;
  - `<h1>` only in `PageHeader`;
  - no `title=` on `Button`/`IconButton`;
  - no `max-w-*` on dialog content;
  - no round icon buttons;
  - German texts without "Sie" and without a lowercase "du".

  Their allowlists may only shrink.

- **Layout spec** (Playwright, `tests/e2e`): every area at 390, 1024 and 1440 px. No horizontal
  overflow, 44 px targets on the phone, no console error.
- **Living style guide:** `/dev/components` (development builds) shows every component in every
  variant and size, in light and dark. A new component or variant is added there first.
- **Review:** every pull request that touches `web/` confirms it follows this document; a deviation
  needs a change of this document in the same pull request.
