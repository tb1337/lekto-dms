# Evaluation set

Synthetic German documents (no real personal data) with the metadata expected of them. They run
through the same signals, judge and fields node as the pipeline, to compare language models and
to check that the checks catch wrong answers.

- `master_data.json`: contacts, document types, tags and fields the documents are matched
  against (a field's `required`: true for a global one, else the types it is required for;
  its `description`: what belongs in it, for the model);
  optionally `topics` (names, or `name` and `parent`), `contact_topics` (the topics each
  contact enables), `contact_aliases` (other names by contact), `contact_identifiers`
  (entered by hand: `kind`, `value` and the `topic` it points to, by contact),
  `type_descriptions` and `title_patterns` (by document type; templates as the rules'
  titles, `{{ contact }}`).
- `training/<name>.md` and `.json`: the training corpus, 57 earlier letters of eleven contacts
  of the set with their metadata, in the style of their cases (as a sender's letters look
  alike), with IBANs, VAT IDs, customer numbers and mail domains, and a `topic` where the
  contact has topics (a person sets it after the takeover: Paperless knows none). The
  household's IBAN stands on letters of several contacts and the utility's also on the bank
  statements: training must learn neither. The insurance group (Hanse Versicherung AG) is
  also the household's employer: its topics are work and three insurances, its personnel
  number and the number of the health insurance policy point to two of them; the health
  insurer's letters all carry its topic, so the domain learned from them points to it.
- `cases/<name>.md`: the document text, as the parse step would produce it (OCR and parsing are
  not part of the evaluation); its structure, the words with their boxes the label check looks
  at, is set from it on a fixed grid, a line per line and a column per character.
- `cases/<name>.json`: `expected` (lane and fields, the topic among them) and `fake`, a fixed
  answer for runs without a model. Some fixed answers are wrong on purpose (`fake.lane` then
  names the lane they must lead to); two cases carry instructions to the model in the text
  (`injection`). `lanes` gives a lane by run where the runs differ; `runs` limits a case to
  some (the pay slip whose employee the model takes for the sender belongs to the trained run:
  before training nothing could catch it). Cases 39 to 42 are about topics: an identifier of
  the pair and the model set it (the employer's pay slip, the health insurance policy), two
  identifiers of different topics leave it empty with both as candidates, and under a contact
  that is only suggested the topic is only suggested. The fixed answers give each field's
  `label`; cases 43 to 45 are about labels (issue #55): a pay slip whose answer takes the base
  salary's line for the gross total and a premium notice whose answer takes a total far below
  the monthly label (both apart from their labels, both passing every other check, yellow only
  for a required field the answer leaves out while the label is only recorded), and an invoice
  whose values stand in columns under their labels (beside).

Every case runs twice, each time on a fresh installation in memory:

- **cold**: no classifier, no similar documents; the language model and the facts in the text
  decide, the rule from before the signals.
- **trained**: the corpus is taken over first as from Paperless (it counts as confirmed),
  indexed with bag-of-words vectors and trained on with scikit-learn, so the classifier, the
  similar documents and the learned identifiers take part.

After each case a simulated person sets the expected values, confirming a yellow document in the
inbox or changing a green one; the log's `corrected` tells which automatic values they changed.

Run it from `backend/`:

```sh
uv run lekto evaluate --fake       # fixed answers, both runs, as in CI
uv run lekto evaluate              # the model in LEKTO_LLM_*
uv run lekto evaluate --runs cold --cases DIR --output FILE
```

A real run needs `LEKTO_LLM_BASE_URL` and `LEKTO_LLM_MODEL`, and a configuration that is valid
otherwise (e.g. `LEKTO_ROLE=worker`). The report goes to `reports/<date>-<model>.md`, the runs
side by side: documents that came out green although they should not have, or with a wrong
value, lanes as expected, run time; per field the hit rate, the values applied without a
person and the share of those the person corrected afterwards (the feedback measure; a topic
only suggested is not applied, its suggestion counts for the hit rate); tag
precision and recall; and per run the lanes expected against lanes got, what the instructions
in the text achieved, each case, and the outcomes of the label check per case and in total
(recorded, not enforced: `beside`, `apart`, label missing, no label, unknown). The command
exits with status 1 if any document came out green that should not have or with a wrong value,
or a field changed without a passed check.

The bag-of-words vectors stand in for an embedding model: the similar documents they find show
that the flow works, not how good real neighbours are. With so small a corpus the trained run
is also strict: a new contact or a type the corpus does not have meets similar documents that
name another value, a contradiction, so yellow.

## Search

`search/queries.json` holds queries for the same documents (`query`, `kind`, `expected`: the
cases that answer it). The kinds are `exact` (words of the document), `number` (identifiers and
amounts), `compound` (compound words), `typo`, `paraphrase` (other words for the same thing),
`english` (query in English, documents in German), `late` (only in the back part of the long
statement, beyond the sections that get a vector), `confusable` (the right one among documents
alike: the pay slips, the electrician's, the mail-order house's, the statements, the insurer's),
`question` (asked as a person asks) and `purpose` (what a document is for, in none of its words).

```sh
uv run lekto evaluate-search --fake                # flow only, as in CI
uv run lekto evaluate-search --models bge-m3,other # models of the endpoint
uv run lekto evaluate-search --ratios 0,0.5,1 --queries FILE --output FILE
```

Each model gets a temporary Meilisearch index (`lekto-eval-…`, removed afterwards) and the
documents of the set, indexed by the real indexing service; the queries run through the real
search service at each semantic ratio. A real run needs `LEKTO_MEILISEARCH_URL`,
`LEKTO_EMBEDDING_BASE_URL` and `LEKTO_EMBEDDING_MODEL` (the default for `--models`), and
`LEKTO_EMBEDDING_DIMENSIONS` with any value, because the configuration is checked first (the
real length is measured). Prefixes, section size and the rest come from the `LEKTO_` settings, so
a model that needs other prefixes gets a run of its own. `--fake` uses bag-of-words vectors and
the in-memory index: it shows that the flow works, not how good a model is.

The documents carry a number as title and file name, so a query cannot find a case by its name.
The report goes to `search/reports/<date>-<models>.md`: Hit@1/3/5 (the share of queries whose
answer is among the first 1, 3 or 5 hits), mean reciprocal rank, time per query, Hit@3 per kind
of query, the cost of indexing (sections, seconds per section) and the queries that missed.
