# Search evaluation 2026-10-21 06:04 - `qwen3-embedding:0.6b`, `hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0`, `hf.co/Qwen/Qwen3-Embedding-8B-GGUF:Q8_0`

- Embedding endpoint: Ollama in the home network (2 vGPUs, the model in video memory)
- Index: Meilisearch at meilisearch:7700, a temporary index per model
- LEKTO_SEARCH_CHUNK_SIZE: `1500`
- LEKTO_SEARCH_MAX_CHUNKS: `8`
- LEKTO_SEARCH_MAX_TEXT: `200000`
- LEKTO_SEARCH_SEMANTIC_RATIO: `0.5`
- LEKTO_EMBEDDING_DOCUMENT_PREFIX: ``
- LEKTO_EMBEDDING_QUERY_PREFIX: `Instruct: Given a search query, retrieve the German personal documents (letters, invoices, statements, contracts) that answer it
Query:`
- Documents: 44, queries: 91
- Result per query: the first expected case among the first 10 hits. Hit@k: the share of queries found within the first k hits; MRR: mean of 1/rank (0 if not found).

## Results

| Model | Ratio | Hit@1 | Hit@3 | Hit@5 | MRR | Mean ms | p95 ms | Without meaning |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen3-embedding:0.6b | 0 | 43% | 51% | 55% | 0.480 | 19 | 54 | 0 |
| qwen3-embedding:0.6b | 0.5 | 88% | 96% | 99% | 0.924 | 108 | 172 | 0 |
| qwen3-embedding:0.6b | 1 | 82% | 92% | 96% | 0.880 | 116 | 172 | 0 |
| hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0 | 0 | 43% | 51% | 55% | 0.480 | 19 | 54 | 0 |
| hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0 | 0.5 | 99% | 100% | 100% | 0.993 | 470 | 682 | 0 |
| hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0 | 1 | 93% | 96% | 98% | 0.948 | 473 | 689 | 0 |
| hf.co/Qwen/Qwen3-Embedding-8B-GGUF:Q8_0 | 0 | 43% | 51% | 55% | 0.480 | 19 | 59 | 0 |
| hf.co/Qwen/Qwen3-Embedding-8B-GGUF:Q8_0 | 0.5 | 97% | 100% | 100% | 0.980 | 686 | 983 | 0 |
| hf.co/Qwen/Qwen3-Embedding-8B-GGUF:Q8_0 | 1 | 91% | 98% | 98% | 0.941 | 688 | 953 | 0 |

Ratio 0 is full text only, 1 is meaning only. 'Without meaning': queries of a ratio above 0 for which the embedding of the query failed, so only the words counted.

## Hit@3 by kind of query

| Model | Ratio | exact (10) | number (5) | compound (6) | typo (2) | paraphrase (17) | english (13) | late (2) | confusable (18) | question (10) | purpose (8) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen3-embedding:0.6b | 0 | 100% | 100% | 67% | 100% | 53% | 8% | 100% | 50% | 0% | 50% |
| qwen3-embedding:0.6b | 0.5 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 89% | 80% | 100% |
| qwen3-embedding:0.6b | 1 | 100% | 60% | 100% | 100% | 100% | 100% | 50% | 89% | 80% | 100% |
| hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0 | 0 | 100% | 100% | 67% | 100% | 53% | 8% | 100% | 50% | 0% | 50% |
| hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0 | 0.5 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0 | 1 | 100% | 60% | 100% | 100% | 100% | 100% | 0% | 100% | 100% | 100% |
| hf.co/Qwen/Qwen3-Embedding-8B-GGUF:Q8_0 | 0 | 100% | 100% | 67% | 100% | 53% | 8% | 100% | 50% | 0% | 50% |
| hf.co/Qwen/Qwen3-Embedding-8B-GGUF:Q8_0 | 0.5 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 100% |
| hf.co/Qwen/Qwen3-Embedding-8B-GGUF:Q8_0 | 1 | 100% | 80% | 100% | 100% | 100% | 100% | 50% | 100% | 100% | 100% |

## Cost of indexing

| Model | Dimensions | Sections | Per document | Embedding s | Rebuild s | s per section |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen3-embedding:0.6b | 1024 | 51 | 1.2 | 17.7 | 18.4 | 0.35 |
| hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0 | 2560 | 51 | 1.2 | 78.4 | 79.5 | 1.54 |
| hf.co/Qwen/Qwen3-Embedding-8B-GGUF:Q8_0 | 4096 | 51 | 1.2 | 125.1 | 126.3 | 2.45 |

## Misses

### qwen3-embedding:0.6b, ratio 0.5

| Query | Kind | Expected | Rank | First hits |
| --- | --- | --- | ---: | --- |
| Barzahlung an den Elektriker | confusable | 38-quittung-ablagenummer | 5 | 32-betrag-deutsch, 44-rechnung-spalten, 03-handwerkerrechnung |
| Kontoauszug, auf dem die Internetrechnung abgebucht wurde | confusable | 30-kontoauszug-fremde-kontakte | 8 | 02-telefonrechnung, 33-optionales-feld-unsinn, 26-langer-kontoauszug |
| Ab wann arbeite ich bei Nordlicht? | question | 07-arbeitsvertrag | 5 | 36-zeitnachweis-monat, 15-lohnabrechnung, 34-betraege-ohne-waehrung |
| Wie viel netto gab es im März? | question | 15-lohnabrechnung, 39-lohnabrechnung-versicherung | 5 | 30-kontoauszug-fremde-kontakte, 33-optionales-feld-unsinn, 02-telefonrechnung |

### hf.co/Qwen/Qwen3-Embedding-4B-GGUF:Q8_0, ratio 0.5

Every query is within the first 3 hits.

### hf.co/Qwen/Qwen3-Embedding-8B-GGUF:Q8_0, ratio 0.5

Every query is within the first 3 hits.
