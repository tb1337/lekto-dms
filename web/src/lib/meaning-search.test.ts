import { afterEach, describe, expect, it, vi } from 'vitest';
import { forgetMeaningSearch, warmSearch } from './meaning-search.ts';

afterEach(() => {
	vi.unstubAllGlobals();
	forgetMeaningSearch();
});

function stub(meaning: boolean) {
	const fetch = vi.fn(async (request: Request) =>
		new URL(request.url).pathname === '/api/v1/pipeline'
			? new Response(
					JSON.stringify({ nodes: [], vision: null, logo_fetch: false, meaning_search: meaning }),
					{
						headers: { 'content-type': 'application/json' }
					}
				)
			: new Response(null, { status: 204 })
	);
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

const warmed = (fetch: ReturnType<typeof stub>) =>
	fetch.mock.calls.filter(([request]) => new URL(request.url).pathname.endsWith('/search/warm'));

describe('warming the search', () => {
	it('asks the API at most once a minute', async () => {
		const fetch = stub(true);
		warmSearch(1_000_000);
		warmSearch(1_030_000);
		warmSearch(1_060_000);
		await vi.waitFor(() => expect(warmed(fetch)).toHaveLength(2));
		expect(warmed(fetch)[0][0].method).toBe('POST');
	});

	it('does nothing without a search by meaning', async () => {
		const fetch = stub(false);
		warmSearch(1_000_000);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
		await new Promise((resolve) => setTimeout(resolve, 10));
		expect(warmed(fetch)).toHaveLength(0);
	});
});
