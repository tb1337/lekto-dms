/**
 * The search by meaning, where the installation has it (`GET /pipeline`: `meaning_search`, asked
 * once): only then does the UI say how a search searched and warm the model while a person
 * types (`POST /documents/search/warm`, at most once a minute from here; the server keeps its
 * own limit), so that the meaning of the query is ready in time. Without it the UI shows
 * nothing of it (Tobi, 24.10.2026).
 */
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';

const EVERY = 60_000;
let warmedAt = -EVERY;
let asked: Promise<boolean> | null = null;

/** Whether the search takes the meaning into account; false if it cannot tell. */
export function meaningSearch(): Promise<boolean> {
	asked ??= unwrap(api.GET('/api/v1/pipeline')).then(
		(pipeline) => pipeline.meaning_search,
		() => {
			asked = null;
			return false;
		}
	);
	return asked;
}

/** Warm the model, if the search has the meaning. */
export function warmSearch(now: number = Date.now()): void {
	if (now - warmedAt < EVERY) return;
	warmedAt = now;
	void meaningSearch().then((meaning) => {
		if (meaning) void api.POST('/api/v1/documents/search/warm').catch(() => {});
	});
}

/** For tests: ask again. */
export function forgetMeaningSearch(): void {
	asked = null;
	warmedAt = -EVERY;
}
