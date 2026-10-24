/**
 * The search by meaning, where the installation has it (`GET /pipeline`: `meaning_search`):
 * only then does the UI say how a search searched and warm the model while a person types
 * (`POST /documents/search/warm`, at most once a minute from here; the server keeps its own
 * limit), so that the meaning of the query is ready in time. Without it the UI shows nothing
 * of it (Tobi, 24.10.2026).
 */
import { api } from '#lib/api/client.ts';
import { forgetPipeline, pipeline } from '#lib/pipeline.ts';

const EVERY = 60_000;
let warmedAt = -EVERY;

/** Whether the search takes the meaning into account; false if it cannot tell. */
export function meaningSearch(): Promise<boolean> {
	return pipeline().then(
		(found) => found.meaning_search,
		() => false
	);
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
	forgetPipeline();
	warmedAt = -EVERY;
}
