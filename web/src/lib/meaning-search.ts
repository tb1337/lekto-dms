/**
 * Get the search ready while a person types: the API has the model of the embeddings loaded, so
 * that the meaning of the query is ready in time (`POST /documents/search/warm`, at most once a
 * minute from here; the server keeps its own limit).
 */
import { api } from '#lib/api/client.ts';

const EVERY = 60_000;
let warmedAt = -EVERY;

export function warmSearch(now: number = Date.now()): void {
	if (now - warmedAt < EVERY) return;
	warmedAt = now;
	void api.POST('/api/v1/documents/search/warm').catch(() => {});
}
