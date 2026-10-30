import { afterEach, describe, expect, it, vi } from 'vitest';
import { goto } from '$app/navigation';
import { goTo, testPage } from '#lib/testing/page-state.svelte.ts';
import { beamTo, closeBeam, openBeam } from './beam.svelte.ts';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

afterEach(() => {
	vi.mocked(goto).mockClear();
	vi.restoreAllMocks();
	goTo('/ui/inbox');
});

describe('the state of the Beam', () => {
	it('opens in a new history entry beside what the entry holds, each document once', () => {
		goTo('/ui/documents', {}, { words: 'Strom' });
		openBeam(['a', 'b', 'a', 'c'], 'c', 'Dokumente');
		expect(goto).toHaveBeenCalledWith('http://lekto/ui/documents', {
			shallow: true,
			state: { words: 'Strom', beam: { ids: ['a', 'b', 'c'], index: 2, from: 'Dokumente' } },
			persistState: true
		});
	});

	it('pages in the same entry, and closes by going back to the entry before', () => {
		const back = vi.spyOn(history, 'back').mockImplementation(() => {});
		goTo('/ui/documents');
		openBeam(['a', 'b'], 'a', 'Dokumente');
		testPage.state = { beam: { ids: ['a', 'b'], index: 0, from: 'Dokumente' } };
		beamTo(1);
		expect(vi.mocked(goto).mock.lastCall?.[1]).toMatchObject({ replace: true });
		beamTo(2); // beyond the last: nothing
		expect(goto).toHaveBeenCalledTimes(2);
		closeBeam();
		expect(back).toHaveBeenCalledOnce();
	});
});
