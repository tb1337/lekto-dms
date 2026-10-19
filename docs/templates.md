# Templates

Lekto writes some texts from the values of a document. These texts are templates in
[Liquid](https://shopify.github.io/liquid/):

- a document type's title pattern;
- the title a rule sets;
- the value of a text field a rule sets;
- the reason of a forced review.

The template editor writes them with you and shows the result on a document you choose.

```liquid
{{ contact }} – {{ document_type }} {{ document_date | date: '%Y-%m' }}
```

`{{ … }}` writes a value. `{% if … %}…{% endif %}` writes a part only under a condition.
`|` passes a value through a filter. Everything else is text as written. Single braces
(`{contact}`, as before 0.2.0) are text too.

The examples below were rendered with `LEKTO_TEMPLATE_LOCALE=de` and
`LEKTO_DEFAULT_CURRENCY=EUR`.

## Values

A template sees the document as the rules leave it, and nothing else: no other documents, no
attributes of objects, no `include` or `render`.

| Value | What it is | Written as |
| --- | --- | --- |
| `title` | the document's title | `Stromrechnung` |
| `filename` | the original's file name without extension | `scan_0042` |
| `original_filename` | the original's file name | `scan_0042.pdf` |
| `contact` | the contact's name | `Stadtwerke Musterstadt` |
| `document_type` | the type's name | `Rechnung` |
| `topic` | the topic's name, not its path | `Arbeit` |
| `document_date` | the document date | `2026-03-14` |
| `added` | the day the document arrived | `2026-03-16` |
| `tags` | the tags set on the document (not those above them), a list sorted by name | `{{ tags \| join: ', ' }}` → `Steuer, Wichtig` |
| `contact_groups` | the groups the contact is in, a list | as `tags` |
| `document_type_groups` | the groups the type is in, a list | as `tags` |
| `space` | the space's name | `Haushalt` |
| `owner` | the owner's user name | `tobi` |
| `channel` | how the document came: `web` (uploaded in the web UI), `api` (with an API token), `migration` (taken over from Paperless-ngx) | `web` |
| `pages` | the number of pages | `2` |
| `field.<key>` | the value of a field, see below | |

A list written without a filter runs its items together (`SteuerWichtig`); join it with
`| join: ', '`.

## Fields

`field.<key>` is the value of a field of the document. The key comes from the field's name:
lower case, umlauts as `ae`, `oe`, `ue` and `ß` as `ss`, other accents dropped, anything else
an underscore, and `f_` before a leading digit. So `LA_Brutto` is `la_brutto` and `Fällig am`
is `faellig_am`. The field management and the template editor show each field's key.

| Data type | `{{ field.x }}` writes | Parts |
| --- | --- | --- |
| Text, choice, link | the text as set | |
| Number | in the locale: `37,5` | |
| Amount | in the locale with its currency: `5.914,00 EUR` | `.amount` (`5914.00`), `.currency` (`EUR`) |
| Date | ISO 8601: `2026-03-14` | |
| Period | ISO 8601 by what it is: `2026-06` (a month), `2026-W38`, `2026-Q3`, `2026`, a day as `2026-09-15`, otherwise both ends as `2026-09-01/2026-09-14` | `.start`, `.end` (dates) |
| Yes or no | `true` or `false` | |

Renaming a field rewrites the templates that use it. A field that a template uses cannot be
deleted.

## Filters

All of [Liquid's standard filters](https://shopify.github.io/liquid/filters/) work, among them:

| Template | Result |
| --- | --- |
| `{{ document_date \| date: '%Y-%m' }}` | `2026-03` |
| `{{ contact \| upcase }}` | `STADTWERKE MUSTERSTADT` |
| `{{ title \| truncate: 10 }}` | `Stromre...` |
| `{{ tags \| join: ', ' }}` | `Steuer, Wichtig` |
| `{{ field.nummer \| default: 'ohne Nummer' }}` | `ohne Nummer` where the field has no value |
| `{{ title \| replace: 'Rechnung', 'RE' }}` | `Strom-RE` for `Strom-Rechnung` |

Three more filters write in `LEKTO_TEMPLATE_LOCALE`:

| Filter | Template | Result |
| --- | --- | --- |
| `datetime` | `{{ document_date \| datetime: format: 'MMMM yyyy' }}` | `März 2026` |
| | `{{ document_date \| datetime: format: 'dd.MM.yyyy' }}` | `14.03.2026` |
| | `{{ field.zeitraum.start \| datetime: format: 'MMMM yyyy' }}` | `Juni 2026` |
| `decimal` | `{{ field.stunden \| decimal }}` | `37,5` |
| `currency` | `{{ field.la_brutto.amount \| currency }}` | `5.914,00 €` |

The `datetime` format uses the
[Unicode date patterns](https://unicode.org/reports/tr35/tr35-dates.html#Date_Field_Symbol_Table):
`d` is the day, `MM` the month as a number, `MMMM` the month's name, `yyyy` the year, and
`QQQ` the quarter (`Q1`). `currency` always writes `LEKTO_DEFAULT_CURRENCY`. For an amount in
another currency, write the amount itself (`{{ field.betrag }}`), which keeps its currency.

## Missing values

A value the document does not have (no contact yet, an empty field) is left out. Writing it
anyway (`{{ field.nummer }}` without a number) sets nothing: the rule's action is skipped,
with the note "field.nummer has no value", and the title stays as it was. Two ways make a part
optional:

```liquid
{{ contact }}{% if field.rechnungsnummer %} – {{ field.rechnungsnummer }}{% endif %}
{{ contact }} {{ field.rechnungsnummer | default: 'ohne Nummer' }}
```

A value that is missing tests as false in `{% if %}`, and `default` takes its place.

When a template is saved, Lekto checks it: Liquid syntax, known filters, and known values
(`unknown value field.brutto` if no field has that key).

## Examples

A pay slip, from its period and gross pay:

```liquid
Entgeltbescheinigung {{ field.leistungszeitraum.start | datetime: format: 'MMMM yyyy' }} – {{ field.la_brutto }}
```

→ `Entgeltbescheinigung Juni 2026 – 5.914,00 EUR`

An invoice, with contact, number and date, the number only where there is one:

```liquid
{{ contact }} Rechnung{% if field.rechnungsnummer %} {{ field.rechnungsnummer }}{% endif %} vom {{ document_date | datetime: format: 'dd.MM.yyyy' }}
```

→ `Stadtwerke Musterstadt Rechnung R-2026-0815 vom 14.03.2026`

A forced review's reason, naming the tags:

```liquid
Bitte prüfen: {{ document_type }} mit {{ tags | join: ', ' | default: 'keinen Tags' }}
```

→ `Bitte prüfen: Rechnung mit keinen Tags` where the document has no tags.

## Limits

- A loop stops after 1,000 turns.
- The output stops after 10,000 characters.
- A title is at most 500 characters.

`POST /api/v1/templates/preview` checks a template and renders it with a document the caller may
read. It also gives that document's values as a template writes them, which is what the template
editor shows.
