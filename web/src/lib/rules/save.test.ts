import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ApiDefinition } from '#lib/rules/model.ts';
import { changeSwitchedOff, createSwitchedOff, GLOBAL } from './save.ts';

const definition = {
	name: 'Telekom',
	priority: 100,
	triggers: ['document_processed'],
	conditions: { all: [] },
	actions: []
} as unknown as ApiDefinition;
const rule = { id: 'r1', enabled: true, name: 'Telekom' };

afterEach(() => vi.unstubAllGlobals());

function stub() {
	const fetch = vi.fn<(request: Request) => Promise<Response>>(
		async () =>
			new Response(JSON.stringify({ ...rule, enabled: false }), {
				headers: { 'content-type': 'application/json' }
			})
	);
	vi.stubGlobal('fetch', fetch);
	return fetch;
}

async function sent(fetch: ReturnType<typeof stub>) {
	return Promise.all(
		fetch.mock.calls.map(async ([request]) => ({
			call: `${request.method} ${new URL(request.url).pathname}`,
			body: await request.clone().json()
		}))
	);
}

describe('saving a rule switched off', () => {
	it('creates a new one switched off in one request: it never runs in between', async () => {
		const fetch = stub();
		await createSwitchedOff(GLOBAL, definition);
		const [only, ...more] = await sent(fetch);
		expect(more).toEqual([]);
		expect(only.call).toBe('POST /api/v1/rules');
		expect(only.body).toMatchObject({ scope: 'global', name: 'Telekom', enabled: false });
	});

	it('saves a change switched off in one request', async () => {
		const fetch = stub();
		await changeSwitchedOff(rule as never, definition, 's1');
		const [only, ...more] = await sent(fetch);
		expect(more).toEqual([]);
		expect(only.call).toBe('PUT /api/v1/rules/r1');
		expect(only.body).toMatchObject({ scope: 'space', space_id: 's1', enabled: false });
	});
});
