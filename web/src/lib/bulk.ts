/**
 * Changing many documents at once (`DocumentsBulkBar`): how the count reads, what an action
 * did, and when reprocessing warns about the model.
 */

import type { components } from '#lib/api/schema.ts';
import { formatNumber } from '#lib/i18n.ts';
import { m } from '#lib/paraglide/messages.js';

type Operation = components['schemas']['BulkOperationOut'];

/** Calls of the language model per document from its step on: the proposal and the facts. */
export const MODEL_CALLS = 2;
/** Documents above which reprocessing from the model's step says what it costs. */
export const WARN_ABOVE = 15;

/** "1 Dokument", "1.234 Dokumente". */
export function bulkDocuments(count: number): string {
	return count === 1 ? m.bulk_documents_one() : m.bulk_documents({ count: formatNumber(count) });
}

/** What an action did: changed, and those that were so already. */
export function bulkResult(operation: Operation): string {
	const changed = formatNumber(operation.changed);
	return operation.unchanged > 0
		? m.bulk_done_unchanged({ changed, unchanged: formatNumber(operation.unchanged) })
		: m.bulk_done({ changed });
}
