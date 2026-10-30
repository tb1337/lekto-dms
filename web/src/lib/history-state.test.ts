import { afterEach, describe, expect, it, vi } from 'vitest';
import { goTo, testPage } from '#lib/testing/page-state.svelte.ts';
import { entryOf } from './history-state.ts';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

afterEach(() => goTo('/ui/admin/master-data'));

describe('a key of the history entry', () => {
	it('stays one object while what it holds stays the same', () => {
		const identifier = entryOf('identifier');
		goTo('/ui/admin/master-data', {}, { identifier: { kind: 'iban', ref: 'r1' } });
		const first = identifier();
		expect(first).toEqual({ kind: 'iban', ref: 'r1' });
		// The Beam opens over it: the entry is new, every key in it too.
		testPage.state = {
			identifier: { kind: 'iban', ref: 'r1' },
			beam: { ids: ['a'], index: 0, from: 'Kennungen' }
		};
		expect(identifier()).toBe(first);
		testPage.state = { identifier: { kind: 'iban', ref: 'r2' } };
		expect(identifier()).toEqual({ kind: 'iban', ref: 'r2' });
		testPage.state = {};
		expect(identifier()).toBeUndefined();
	});
});
