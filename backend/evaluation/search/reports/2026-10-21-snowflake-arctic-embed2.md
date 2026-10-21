# Search evaluation 2026-10-21 06:03 - `snowflake-arctic-embed2:latest`

- Embedding endpoint: Ollama in the home network (2 vGPUs, the model in video memory)
- Index: Meilisearch at meilisearch:7700, a temporary index per model
- LEKTO_SEARCH_CHUNK_SIZE: `1500`
- LEKTO_SEARCH_MAX_CHUNKS: `8`
- LEKTO_SEARCH_MAX_TEXT: `200000`
- LEKTO_SEARCH_SEMANTIC_RATIO: `0.5`
- LEKTO_EMBEDDING_DOCUMENT_PREFIX: ``
- LEKTO_EMBEDDING_QUERY_PREFIX: `query:`
- Documents: 44, queries: 91
- Result per query: the first expected case among the first 10 hits. Hit@k: the share of queries found within the first k hits; MRR: mean of 1/rank (0 if not found).

## Results

| Model | Ratio | Hit@1 | Hit@3 | Hit@5 | MRR | Mean ms | p95 ms | Without meaning |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| snowflake-arctic-embed2:latest | 0 | 43% | 51% | 55% | 0.480 | 18 | 53 | 0 |
| snowflake-arctic-embed2:latest | 0.5 | 92% | 99% | 100% | 0.955 | 137 | 188 | 0 |
| snowflake-arctic-embed2:latest | 1 | 89% | 97% | 98% | 0.929 | 126 | 191 | 0 |

Ratio 0 is full text only, 1 is meaning only. 'Without meaning': queries of a ratio above 0 for which the embedding of the query failed, so only the words counted.

## Hit@3 by kind of query

| Model | Ratio | exact (10) | number (5) | compound (6) | typo (2) | paraphrase (17) | english (13) | late (2) | confusable (18) | question (10) | purpose (8) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| snowflake-arctic-embed2:latest | 0 | 100% | 100% | 67% | 100% | 53% | 8% | 100% | 50% | 0% | 50% |
| snowflake-arctic-embed2:latest | 0.5 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 94% | 100% | 100% |
| snowflake-arctic-embed2:latest | 1 | 100% | 100% | 100% | 100% | 100% | 100% | 0% | 94% | 100% | 100% |

## Cost of indexing

| Model | Dimensions | Sections | Per document | Embedding s | Rebuild s | s per section |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| snowflake-arctic-embed2:latest | 1024 | 51 | 1.2 | 17.7 | 19.1 | 0.35 |

## Misses

### snowflake-arctic-embed2:latest, ratio 0.5

| Query | Kind | Expected | Rank | First hits |
| --- | --- | --- | ---: | --- |
| Kontoauszug, auf dem die Internetrechnung abgebucht wurde | confusable | 30-kontoauszug-fremde-kontakte | 4 | 02-telefonrechnung, 33-optionales-feld-unsinn, 12-kreditkartenabrechnung |
