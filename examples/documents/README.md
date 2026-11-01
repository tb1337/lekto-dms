# Example documents

321 synthetic documents of one household, in every quality stage Lekto meets: born-digital PDFs,
program printouts, scans from clean to poor, faxes, phone photos and screenshots. Use them to try
Lekto end to end (OCR, the vision language model, codes, facts, relations, series, training)
and for screenshots, without private data. `manifest.json` says what is in each file.

Everything is made up: the people, companies, authorities, addresses and amounts. Domains end in
`.example`; IBANs, tax IDs, social security, health insurance and VAT numbers are invented with
valid check digits, so that Lekto recognises them. Any likeness to a real account is chance.

## The household

Max Mustermann, Erika Musterfrau and their daughter Lena (born 2017) live in Musterstadt. On
1 August 2025 they moved from Birkenweg 5 to Lindenallee 12, so letters before and after carry
different addresses. Max is a design engineer at Brückner Maschinenbau; Erika changed from a
bookshop to the city library in March 2025. The documents run from January 2024 to October 2026
and come from 54 senders: utilities, a telephone company, landlords, craftsmen, shops,
banks, insurers, authorities, doctors, a club, schools, a few in English.

## What is in it

- **Invoices and around them:** power bills (an annual bill, a final bill at the move, a
  correction), monthly telephone bills, craftsmen, doctors and a dentist, the garage, mail
  order and online shops, hosting and software in English, a hotel in Bristol; offers, order
  confirmations, delivery notes, reminders (first and second), a credit note.
- **Receipts:** till receipts of a supermarket, a DIY store, a drugstore, a bakery, a café, a
  petrol station and a pharmacy; cash receipts from a pad and a private sale, filled in by hand.
- **Bank:** monthly account statements (2024 from the statement printer), credit card
  statements, a partner's quarterly statements, a car loan, a building society, tax
  certificates, SEPA mandates, a transfer confirmation in online banking.
- **Work:** pay slips of both employers, annual wage tax certificates, an employment contract,
  salary letters, references, a termination, monthly time sheets.
- **Housing:** the lease and the cooperative's membership, the landlord's confirmation for the
  registration office, utility statements, a rent increase; the old landlord's confirmation of
  the notice and the deposit.
- **Insurance:** household contents, liability and car policies, premium invoices and
  adjustments, a claim from the report by hand to the settlement, the health insurer, a pension
  policy.
- **Authorities:** income tax assessments and the tax office's request, motor vehicle tax, the
  registration certificate, dog tax, child benefit, pension information, a fine with its
  hearing.
- **Health and everyday life:** a discharge letter, findings, a sick note; the sports club, a
  donation receipt, train and plane tickets, a lawyer's letters, the music school, the primary
  school, an evening class, advertising, a licence certificate, and one blank page scanned by
  mistake.

Documents relate as in life: an order, its delivery note, invoice, credit note and two
reminders; an offer and its invoice; a policy, its claim and the settlement; a letter answering
"Ihr Schreiben vom …". Two documents are in the corpus twice (a bill as PDF and as a stamped
scan, a contract scanned and photographed).

## Quality stages

| Stage | What it is | Files |
| --- | --- | --- |
| `digital` | A PDF from a portal or by e-mail: text in the PDF standard fonts, vector graphics | PDF |
| `printout` | A program's printout as PDF: Courier lines, tables of `|` and `-` | PDF |
| `scan-clean` | A flatbed scan at 200 dpi in greyscale, straight, white paper | PDF (JPEG) |
| `scan-office` | An office scanner at 150 dpi in colour, a little askew, sometimes both sides with the blank backs | PDF (JPEG) |
| `scan-bw` | A bilevel scan at 300 dpi; two as multi-page TIFF | PDF (CCITT G4), TIFF |
| `scanner-ocr` | A scan with the scanner's own invisible text, about one word in eight misread (`ü` as `u`, `l` as `1`) | PDF (JPEG and text) |
| `fax` | A fax at 204 × 98 dpi: header line, streaks, lost thin strokes | PDF (CCITT G4) |
| `scan-poor` | 100 dpi, a shadow, noise, blur, strong JPEG, tilted by up to 3° | PDF (JPEG) |
| `photo` | A phone photo on a table: at an angle, light from one side, a shadow at the edges | JPEG; PDF for several pages |
| `photo-poor` | Dark, shaken, a glare, one corner cut off | JPEG; PDF for several pages |
| `screenshot` | A web page in the browser or a PDF in a viewer, cut off at the bottom | PNG |

Receipts on a scanner lie on the glass with the lid around them. What a person did to the paper
is in `marks`: `stamp` ("BEZAHLT" with a date), `highlight`, `note` (by hand), `holes`, `folds`,
`stain`, `staple`. One pay slip was fed upside down (`capture.turned_pages`), two photos lie on
their side with an EXIF orientation (`capture.exif_orientation`).

File names are what the source gives: `Rechnung_R-2026-0815.pdf` from a portal,
`Scan_2025-08-06_092946.pdf` from a scanner, `IMG_20250820_204836.jpg` from a phone,
`Fax_+491234515253_20251115-1814.pdf`. A name tells nothing about the content; the manifest
does.

## The manifest

`manifest.json` holds one entry per file, in the JSON forms of Lekto's API:

- `file`, `key` (stable, for scripts), `class` (the finer kind, such as `utility-bill`),
  `quality` (the stage), `layout` (`letter`, `printout`, `receipt`, `form`, `screen`, `ticket`,
  …), `media_type`, `pages`, `language`.
- What Lekto should decide: `contact`, `document_type` (a suggested type name, such as
  `Rechnung`), `document_date`, `title`, `recipient` (`max`, `erika`, `lena` or `max+erika`)
  and `fields` by name (`Betrag` as `{"amount": "84.20", "currency": "EUR"}`, dates as
  `2026-04-15`, periods as `2026-03`, `2025` or `2025-08-01/2026-07-31`).
- `facts`: the identifiers the document shows, each with Lekto's `kind`, the `value` as written
  and its `role` (`own`, `contact`, `target`, `thread`, `refers`, `person`). `"pattern": false`
  marks one Lekto's patterns do not read as written (a printer's `ZAEHLERNR.`), only a model.
- `codes` (the formats on the pages), `relations` (the files it refers to), `series`
  (`sparkasse`, `fernnetz`, `lohn-max`, …), `duplicate_of`, `marks`, `capture`.

## Using them

Upload the files in `files/` through the web UI (several at once) or `POST /api/v1/documents`.
All of them make several hundred jobs, among them OCR for about 150 files: try a handful first.
There is no master data for them yet; Lekto proposes contacts and types itself.

## Generating them again

The generator is `generate.py` with the package `synth/`. It uses only the backend's
dependencies (Pillow, numpy, zxing-cpp, pikepdf) and Ghostscript's URW fonts, so run it in the
devcontainer from `backend/`:

```sh
uv run python ../examples/documents/generate.py --check   # lay out, check identifiers and margins
uv run python ../examples/documents/generate.py           # write files/, manifest.json, the statistics below
```

The output is deterministic: the same code gives the same bytes, so only what changed shows up
in Git. `--check` finds each identifier of the manifest in the document's text with Lekto's own
patterns (`identifiers_in`) and reports text that runs off its page; the generator refuses to
write while it finds anything. Classes live in `synth/classes/`, the plan of the corpus (what,
when, which stage, which marks, which relations) in `synth/corpus.py`.

## Statistics

<!-- statistics -->
321 documents, 362 pages, 12.8 MB.

| Quality stage | Documents |
| --- | ---: |
| `digital` | 156 |
| `printout` | 7 |
| `scan-clean` | 26 |
| `scan-office` | 43 |
| `scan-bw` | 25 |
| `scanner-ocr` | 13 |
| `fax` | 4 |
| `scan-poor` | 11 |
| `photo` | 21 |
| `photo-poor` | 10 |
| `screenshot` | 5 |

| Document type | Documents |
| --- | ---: |
| Rechnung | 72 |
| Kontoauszug | 48 |
| Lohnabrechnung | 46 |
| Kassenbon | 38 |
| Mitteilung | 20 |
| Kreditkartenabrechnung | 12 |
| Vertrag | 11 |
| Bescheinigung | 10 |
| Bescheid | 9 |
| Versicherung | 9 |
| Zeitnachweis | 9 |
| Ticket | 6 |
| Abrechnung | 3 |
| Lohnsteuerbescheinigung | 3 |
| Mahnung | 3 |
| Quittung | 3 |
| Angebot | 2 |
| Arztbrief | 2 |
| Bestellbestätigung | 2 |
| Kündigung | 2 |
| Lieferschein | 2 |
| Spendenbescheinigung | 2 |
| Werbung | 2 |
| Zeugnis | 2 |
| Garantie | 1 |
| Gutschrift | 1 |

| Class | Documents | Class | Documents |
| --- | ---: | --- | ---: |
| `account-statement` | 44 | `loan-contract` | 1 |
| `advertising` | 2 | `loan-statement` | 2 |
| `blank` | 1 | `membership` | 1 |
| `boarding-pass` | 1 | `membership-certificate` | 1 |
| `card-statement` | 12 | `meter-reading` | 1 |
| `cash-receipt` | 3 | `music-contract` | 1 |
| `child-benefit` | 2 | `offer` | 2 |
| `claim-letter` | 2 | `order-confirmation` | 2 |
| `claim-report` | 1 | `payslip` | 46 |
| `club-fee` | 1 | `pension-information` | 3 |
| `club-membership` | 1 | `pension-statement` | 1 |
| `contract-confirmation` | 1 | `phone-bill` | 33 |
| `contribution-change` | 1 | `premium-adjustment` | 1 |
| `course-confirmation` | 1 | `premium-invoice` | 3 |
| `craftsman-invoice` | 4 | `price-change` | 2 |
| `credit-note` | 1 | `private-sale` | 1 |
| `delivery-note` | 2 | `purchase-contract` | 1 |
| `deposit-statement` | 1 | `reference` | 2 |
| `discharge-letter` | 1 | `registration` | 1 |
| `doctor-invoice` | 3 | `reminder` | 3 |
| `dog-tax` | 2 | `rent-increase` | 1 |
| `donation-receipt` | 2 | `salary-change` | 2 |
| `employment-contract` | 2 | `savings-contract` | 1 |
| `exemption-order` | 1 | `savings-statement` | 2 |
| `family-insurance` | 1 | `school-letter` | 2 |
| `fee-statement` | 1 | `sepa-mandate` | 2 |
| `findings` | 1 | `shop-invoice` | 3 |
| `fine` | 1 | `sick-note` | 1 |
| `fine-hearing` | 1 | `software-invoice` | 1 |
| `flight-booking` | 1 | `tax-certificate` | 1 |
| `garage-invoice` | 2 | `tax-office-letter` | 1 |
| `hosting-invoice` | 14 | `termination` | 2 |
| `hotel-invoice` | 1 | `till-receipt` | 38 |
| `income-tax-assessment` | 2 | `time-sheet` | 9 |
| `inspection-report` | 1 | `train-ticket` | 4 |
| `insurance-notice` | 1 | `transfer-confirmation` | 1 |
| `insurance-policy` | 3 | `treatment-plan` | 1 |
| `invoice-correction` | 1 | `utility-bill` | 5 |
| `landlord-confirmation` | 1 | `utility-statement` | 2 |
| `lawyer-letter` | 2 | `vehicle-tax` | 2 |
| `lease` | 1 | `wage-tax-certificate` | 3 |
| `licence-certificate` | 1 | `warranty` | 1 |

| File type | Documents |
| --- | ---: |
| application/pdf | 284 |
| image/jpeg | 30 |
| image/png | 5 |
| image/tiff | 2 |
<!-- /statistics -->
