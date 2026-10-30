import { render, screen } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { goto } from '$app/navigation';
import { m } from '#lib/paraglide/messages.js';
import { goTo } from '#lib/testing/page-state.svelte.ts';
import DocumentBackLink from './DocumentBackLink.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

afterEach(() => {
	vi.mocked(goto).mockClear();
	vi.restoreAllMocks();
	goTo('/ui/inbox');
});

describe('DocumentBackLink', () => {
	it('goes back in the history to the place a jump came from, naming it', async () => {
		const back = vi.spyOn(history, 'back').mockImplementation(() => {});
		goTo('/ui/documents/a', {}, { from: { label: 'Eingang' } });
		render(DocumentBackLink, { inbox: true });
		await userEvent.click(screen.getByRole('link', { name: m.back_to({ place: 'Eingang' }) }));
		expect(back).toHaveBeenCalledOnce();
		expect(goto).not.toHaveBeenCalled();
	});

	it('leads to the inbox or the list without a jump', () => {
		goTo('/ui/documents/a');
		render(DocumentBackLink, { inbox: true });
		expect(screen.getByRole('link', { name: m.nav_inbox() }).getAttribute('href')).toBe(
			'/ui/inbox'
		);
	});
});
