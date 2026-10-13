import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { goto } from '$app/navigation';
import { m } from '#lib/paraglide/messages.js';
import HeaderSearch from './HeaderSearch.svelte';

const state = vi.hoisted(() => ({ url: new URL('http://papiq/ui/inbox') }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', () => ({
	page: {
		get url() {
			return state.url;
		}
	}
}));

beforeEach(() => {
	vi.mocked(goto).mockClear();
	state.url = new URL('http://papiq/ui/inbox');
});

describe('HeaderSearch', () => {
	it('opens the search page with the words', async () => {
		render(HeaderSearch);
		const field = screen.getByRole('searchbox', { name: m.header_search_label() });
		await userEvent.type(field, ' Stromrechnung März {Enter}');
		expect(goto).toHaveBeenCalledWith('/ui/search?q=Stromrechnung+M%C3%A4rz');
	});

	it('keeps the filters of the search page', async () => {
		state.url = new URL('http://papiq/ui/search?q=alt&tag=7');
		render(HeaderSearch);
		const field = screen.getByRole('searchbox', { name: m.header_search_label() });
		expect((field as HTMLInputElement).value).toBe('alt');
		await userEvent.clear(field);
		await userEvent.type(field, 'neu{Enter}');
		expect(goto).toHaveBeenCalledWith('/ui/search?q=neu&tag=7');
	});

	it('takes the focus on / unless one types elsewhere', async () => {
		render(HeaderSearch);
		const field = screen.getByRole('searchbox', { name: m.header_search_label() });
		await userEvent.keyboard('/');
		expect(document.activeElement).toBe(field);
		expect((field as HTMLInputElement).value).toBe('');
	});
});
