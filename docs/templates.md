# Templates

Lekto writes some texts from the values of a document. These texts are templates in
[Liquid](https://shopify.github.io/liquid/):

- a document type's title pattern;
- the title a rule sets;
- the value of a field a rule sets, of any type (see [Setting a field](#setting-a-field));
- the reason of a forced review;
- the body of a webhook with the body `template` (it has to make JSON; see
  [Webhook bodies](#webhook-bodies)).

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
| `space` | the space's name; a personal space by its user's name | `Haushalt` |
| `uploaded_by` | who uploaded it, by display name (else user name; no rights come with it; until 0.5 `owner`) | `Tobias Example` |
| `channel` | how the document came: `web` (uploaded in the web UI), `api` (with an API token), `migration` (taken over from Paperless-ngx) | `web` |
| `pages` | the number of pages | `2` |
| `field.<key>` | the value of a field, see below | |
| `steps.<name>` | in a rule's step: what a step before it that asks a webhook brought (its answer, JSON: objects with `.key`, lists with `.0`, …); missing without an answer | `{{ steps.accounting.beleg }}` → `B-4711` |

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

## Facts

The numbers and references a document shows (its facts: invoice number, customer number, the
invoice a reminder refers to, ...) are no fields, but a template sees them, so a rule can put
one into a field:

| Value | Writes |
| --- | --- |
| `facts.<kind>` | the document's own value of the kind, the first as the text reads, as the text writes it: `{{ facts.invoice_number }}` |
| `facts.refers.<kind>` | the first value of the kind that refers to another document: `Mahnung zu Rechnung {{ facts.refers.invoice_number }}` |
| `facts.girocode.<part>` | the first GiroCode on the pages: `amount` (an amount), `iban`, `name`, `bic`, `purpose` |
| `fact_list` | every fact, each with `kind`, `value` (normalised, as Lekto compares it), `written` (as the text writes it), `role` and `origin` (`person`, `model`, `pattern` or `code`): `{{ fact_list \| where: "kind", "iban" \| map: "value" \| join: ", " }}` |

The kinds are fixed in the code and English (`invoice_number`, `customer_number`,
`contract_number`, `letter_date`, ...); the template editor offers them with their names. A
fact a person rejected is missing, one they corrected gives their value. A person's numbers
alone (tax ID, social security number, ...) are not among them. Without the fact, writing it
is a missing value: the action sets nothing (noted, not yellow).

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

`json` writes a value as JSON, as the API writes it, for the body of a webhook: text in quotes
with what needs escaping escaped, a number as its exact decimal text (`"37.5"`), an amount as
`{"amount": "5914.00", "currency": "EUR"}`, a date as `"2026-03-14"`, a period as
`{"start": …, "end": …}`, yes/no as `true` or `false`, a list as a list.

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

## Setting a field

A rule sets a field of any type with a template. What the template writes is read as the
field's type has it, the way Lekto reads a value a document shows:

1. First the forms templates write themselves: a number as its decimal text (`1234.5`, `.5`;
   `1.234` is one point two three four), a day in ISO 8601 (`2026-03-14`), a period as above
   (`2026-Q3`, `2026-W38`, `2026-09-01/2026-09-14`; `2026-Q5` is none), yes or no as `true` or
   `false`, an amount as a number with a currency code (ISO 4217) before or after it, or without
   one.
2. Otherwise as a person writes it: `2.111,68 €`, `3.650,00 EUR`, `14. März 2026`, `14.03.26`,
   `KW 38/2026`, `September 2026`, `ja`, `nein`. A number that reads two ways (`1.234`)
   counts as the language of `LEKTO_TEMPLATE_LOCALE` means it; an amount without a currency
   is in `LEKTO_DEFAULT_CURRENCY`; a two-digit year is the reading nearest to the day the
   document came in.

| Type | Template | The field gets |
| --- | --- | --- |
| Amount | `{{ field.la_brutto }}` | `5914.00 EUR` |
| Amount | `{{ steps.accounting.total }} {{ steps.accounting.currency }}` | `84.20 EUR` |
| Date | `{{ document_date }}` | `2026-03-14` |
| Number | `{{ field.stunden \| times: 2 }}` (37,5 hours) | `75.0` |
| Yes/no | `{% if tags contains 'Bezahlt' %}ja{% else %}nein{% endif %}` | yes |
| Choice | `{{ steps.crm.status }}` | `offen`, if it is one of the options |
| Period | `{{ field.leistungszeitraum }}` | `2026-06` |

What cannot be read sets nothing, like a missing value: the action is skipped with the note
"'later' cannot be read as a date", and the document does not wait for a person because of it.
A number or an amount is only the value, without words but a currency's: `7 Stück` is no
number, `Fällig in 14 Tagen` no amount (`{{ x | remove: ' Stück' }}` takes the word out). A
period without a year (`September`) is not read: a rule does not guess the year. A choice
must be one of the field's options as written; an option is a fixed value even where it holds
braces. Text without `{{` or `{%` writes itself and is
read when the rule is saved: `12,50 €` is a fixed amount, `zwölf` is refused. The template
editor shows what the field gets from the document you chose. In the rule builder a field
that is not text has a fixed value or a template; an amount, a period or yes/no given as JSON
over the API stays a fixed value.

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

## Webhook bodies

A webhook with the body `template` sends what its template makes, which has to be JSON. Besides
the values above it sees:

| Value | Content |
| --- | --- |
| `event.type`, `event.id`, `event.occurred_at` | the event (`document.filed`, …, `rule.send` for a rule's request) |
| `document_id` | the document's ID |
| `lane` | `green`, `yellow` or `red`; missing while it is processed |
| `link` | the document in the web UI (`LEKTO_PUBLIC_URL/ui/documents/<id>`); missing without `LEKTO_PUBLIC_URL` |
| `rule.id`, `rule.name` | the rule that sends or asks; missing for an event |
| `task.id`, `task.callback`, `task.token`, `task.deadline` | a task's request (it expects an answer): where and with which token to answer, and by when; missing otherwise |
| `steps.<name>` | in a task of a rule's step: what the rule's steps before brought; missing otherwise |

Write every value with `json`, and a value that may be missing with `| default: nil | json`
(`null` then). A Home Assistant notification:

```liquid
{"title": {{ document_type | default: "Dokument" | json }},
 "message": {{ title | json }},
 "amount": {{ field.betrag.amount | default: nil | json }},
 "url": {{ link | default: nil | json }}}
```

→ `{"title": "Rechnung", "message": "Strom März", "amount": "120.50", "url": "https://…"}`

The template is rendered as written, whitespace kept. A request whose template does not make
JSON, or writes a missing value, is not sent; the webhook's log says why.

## Limits

- A loop stops after 1,000 turns.
- The output stops after 10,000 characters.
- A title is at most 500 characters, a webhook's body template 10,000.

`POST /api/v1/templates/preview` checks a template and renders it with a document the caller may
read. It also gives that document's values as a template writes them, which is what the template
editor shows. With `purpose: webhook` it checks a webhook's body template: with the values above,
as written, and whether it makes JSON.
