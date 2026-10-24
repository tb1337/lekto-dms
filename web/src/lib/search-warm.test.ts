import { afterEach, describe, expect, it, vi } from 'vitest';
import { warmSearch } from './search-warm.ts';

afterEach(() => vi.unstubAllGlobals());

describe('warming the search', () => {
	it('asks the API at most once a minute', async () => {
		const fetch = vi.fn(async () => new Response(null, { status: 204 }));
		vi.stubGlobal('fetch', fetch);
		warmSearch(1_000_000);
		warmSearch(1_030_000);
		warmSearch(1_060_000);
		await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
		const [request] = fetch.mock.calls[0] as unknown as [Request];
		expect(`${request.method} ${new URL(request.url).pathname}`).toBe(
			'POST /api/v1/documents/search/warm'
		);
	});
});
