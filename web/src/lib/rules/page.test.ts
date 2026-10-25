import { afterEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { calls, fakeApi, json } from '#lib/testing/documents.ts';
import { RuleLoader } from './page.svelte.ts';

afterEach(() => vi.unstubAllGlobals());

const lookups = (api: ReturnType<typeof fakeApi>) =>
	calls(api).filter((call) => call === 'GET /api/v1/users').length;

describe('the loader of a rule page', () => {
	it('loads the data beside the master data, kept until asked for anew', async () => {
		const api = fakeApi();
		vi.stubGlobal('fetch', api);
		const loader = new RuleLoader();
		const then = vi.fn();
		await loader.load(() => Promise.resolve('first'), then);
		expect(then).toHaveBeenCalledWith('first', loader.lookup);
		expect(loader.lookup?.users).toEqual([]);
		expect(loader.problem).toBeNull();
		expect(lookups(api)).toBe(1);

		await loader.load(() => Promise.resolve('second'), then);
		expect(lookups(api)).toBe(1);
		await loader.load(() => Promise.resolve('third'), then, { fresh: true });
		expect(lookups(api)).toBe(2);
		expect(then).toHaveBeenCalledTimes(3);
	});

	it('drops an answer a later load overtook', async () => {
		vi.stubGlobal('fetch', fakeApi());
		const loader = new RuleLoader();
		let release = () => {};
		const slow = new Promise<string>((resolve) => (release = () => resolve('slow')));
		const then = vi.fn();
		const first = loader.load(() => slow, then);
		await loader.load(() => Promise.resolve('fast'), then);
		release();
		await first;
		expect(then).toHaveBeenCalledTimes(1);
		expect(then).toHaveBeenCalledWith('fast', loader.lookup);
	});

	it('says what went wrong, and clears it with the next load that works', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({ 'GET /api/v1/users': () => json({ detail: 'Not allowed.', status: 403 }, 403) })
		);
		const loader = new RuleLoader();
		const then = vi.fn();
		await loader.load(() => Promise.resolve('data'), then);
		expect(then).not.toHaveBeenCalled();
		expect(loader.problem).toContain(m.error_forbidden());
		expect(loader.lookup).toBeNull();

		vi.stubGlobal('fetch', fakeApi());
		await loader.load(() => Promise.resolve('data'), then);
		expect(loader.problem).toBeNull();
		expect(then).toHaveBeenCalledOnce();
	});
});
