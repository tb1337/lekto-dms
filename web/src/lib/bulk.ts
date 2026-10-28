/**
 * Changing many documents at once (`DocumentsBulkBar`): how the count reads, what an action
 * did, and when reprocessing warns about the model.
 */

import type { components } from '#lib/api/schema.ts';
import { usageLabel } from '#lib/components/UsageCount.svelte';
import { formatNumber } from '#lib/i18n.ts';
import { m } from '#lib/paraglide/messages.js';

type Operation = components['schemas']['BulkOperationOut'];

/** The most documents one action takes, as the API takes it (mirrors `MAX_DOCUMENTS` in
 * `backend/src/lekto/core/domain/bulk.py`). */
export const MAX_DOCUMENTS = 10_000;
/** The most hits a search by words reaches (mirrors `MAX_HITS` in
 * `backend/src/lekto/core/ports/search_index.py`). */
export const MAX_HITS = 1_000;
/** Calls of the language model per document from its step on: the proposal and the facts. */
export const MODEL_CALLS = 2;
/** Documents above which reprocessing from the model's step says what it costs. */
export const WARN_ABOVE = 15;

/** "1 Dokument", "1.234 Dokumente", as the master data count theirs. */
export function bulkDocuments(count: number): string {
	return usageLabel(count);
}

/** What an action did: changed, and those that were so already. */
export function bulkResult(operation: Operation): string {
	const changed = formatNumber(operation.changed);
	return operation.unchanged > 0
		? m.bulk_done_unchanged({ changed, unchanged: formatNumber(operation.unchanged) })
		: m.bulk_done({ changed });
}
