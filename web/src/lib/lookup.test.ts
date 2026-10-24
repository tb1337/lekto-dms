import { afterEach, describe, expect, it, vi } from 'vitest';
import { fakeApi, json } from '#lib/testing/documents.ts';
import { PageLookup } from './lookup.svelte.ts';

afterEach(() => vi.unstubAllGlobals());

const USERS = [{ id: 'u1', username: 'tobi', role: 'user', active: true }];

describe('the master data of a page', () => {
	it('keeps the newest answer, not the slowest', async () => {
		let releaseFirst = () => {};
		const first = new Promise<Response>((resolve) => {
			releaseFirst = () => resolve(json([]));
		});
		let asked = 0;
		vi.stubGlobal('fetch', fakeApi({ 'GET /api/v1/users': () => (++asked === 1 ? first : USERS) }));
		const lookup = new PageLookup();
		const slow = lookup.load();
		await lookup.load();
		expect(lookup.value?.users).toEqual(USERS);
		releaseFirst();
		await slow;
		expect(lookup.value?.users).toEqual(USERS);
	});

	it('tells a listener of a failure and clears it with the next load', async () => {
		const onerror = vi.fn();
		vi.stubGlobal(
			'fetch',
			fakeApi({ 'GET /api/v1/users': () => json({ detail: 'Down', status: 503 }, 503) })
		);
		const lookup = new PageLookup(onerror);
		await lookup.load();
		expect(lookup.value).toBeNull();
		expect(lookup.problem).toBeTruthy();
		expect(onerror).toHaveBeenCalledOnce();

		vi.stubGlobal('fetch', fakeApi());
		await lookup.load();
		expect(lookup.problem).toBeNull();
		expect(lookup.value?.users).toEqual([]);
	});
});
