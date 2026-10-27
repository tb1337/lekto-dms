import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { goto } from '$app/navigation';
import { m } from '#lib/paraglide/messages.js';
import { openLens } from '#lib/open-lens.svelte.ts';
import HeaderSearch from './HeaderSearch.svelte';

const state = vi.hoisted(() => ({ url: new URL('http://lekto/ui/inbox') }));
vi.mock('$app/navigation', () => ({ beforeNavigate: vi.fn(), goto: vi.fn() }));
vi.mock('$app/state', () => ({
	page: {
		get url() {
			return state.url;
		}
	}
}));

beforeEach(() => {
	vi.mocked(goto).mockClear();
	state.url = new URL('http://lekto/ui/inbox');
});

describe('HeaderSearch', () => {
	it('searches the documents with the words', async () => {
		render(HeaderSearch);
		const field = screen.getByRole('searchbox', { name: m.header_search_label() });
		await userEvent.type(field, ' Stromrechnung März {Enter}');
		expect(goto).toHaveBeenCalledWith('/ui/documents?q=Stromrechnung+M%C3%A4rz');
	});

	it('names the lens the document view has open, and keeps it', async () => {
		state.url = new URL('http://lekto/ui/documents?lens=l1&tag=7');
		openLens.name = 'Zu bezahlen';
		try {
			render(HeaderSearch);
			const field = screen.getByRole('searchbox', { name: m.header_search_label() });
			expect(field.getAttribute('placeholder')).toBe(m.header_search_in({ name: 'Zu bezahlen' }));
			await userEvent.type(field, 'Strom{Enter}');
			expect(goto).toHaveBeenCalledWith('/ui/documents?lens=l1&tag=7&q=Strom');
		} finally {
			openLens.name = null;
		}
	});

	it('keeps the filters of the document view, the sort goes with the search', async () => {
		state.url = new URL('http://lekto/ui/documents?q=alt&tag=7&sort=title');
		render(HeaderSearch);
		const field = screen.getByRole('searchbox', { name: m.header_search_label() });
		expect((field as HTMLInputElement).value).toBe('alt');
		await userEvent.clear(field);
		await userEvent.type(field, 'neu{Enter}');
		expect(goto).toHaveBeenCalledWith('/ui/documents?q=neu&tag=7');
	});

	it('takes the focus on / unless one types elsewhere', async () => {
		render(HeaderSearch);
		const field = screen.getByRole('searchbox', { name: m.header_search_label() });
		await userEvent.keyboard('/');
		expect(document.activeElement).toBe(field);
		expect((field as HTMLInputElement).value).toBe('');
	});
});
