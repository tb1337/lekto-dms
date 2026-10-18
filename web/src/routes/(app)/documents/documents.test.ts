import { render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { rememberView } from '#lib/listing.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi, listedOf, OWNER } from '#lib/testing/documents.ts';
import Page from './+page.svelte';

const state = vi.hoisted(() => ({ url: new URL('http://papiq/ui/documents') }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', () => ({
	page: {
		get url() {
			return state.url;
		}
	}
}));

beforeEach(() => {
	state.url = new URL('http://papiq/ui/documents');
	session.start({
		user: { id: OWNER, username: 'tobi', role: 'user' },
		method: 'password',
		expires_at: '2026-10-18T12:00:00Z',
		csrf_token: 'token'
	});
	// Rows: their mark stands beside their link (the grid's is tested with the card).
	rememberView('list');
});

afterEach(() => {
	rememberView('grid');
	session.clear();
	vi.unstubAllGlobals();
});

describe('the archive page', () => {
	it('lists without lanes and upload, and marks what stands in the inbox', async () => {
		const api = fakeApi({
			'GET /api/v1/documents': () => ({
				items: [
					listedOf({ id: 'd1', title: 'Wartet', lane: 'red', in_inbox: true }),
					listedOf({ id: 'd2', title: 'Abgelegt', lane: 'green', in_inbox: false })
				],
				next_cursor: null
			})
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		const waiting = (await screen.findByText('Wartet')).closest('li')!;
		const filed = screen.getByText('Abgelegt').closest('li')!;
		expect(within(waiting).getByRole('link', { name: m.in_inbox() }).getAttribute('href')).toBe(
			'/ui/inbox?tab=intervene'
		);
		expect(within(filed).queryByRole('link', { name: m.in_inbox() })).toBeNull();
		expect(document.querySelector('[data-lane]')).toBeNull();
		expect(screen.queryByRole('button', { name: m.upload_title() })).toBeNull();
		expect(screen.queryByRole('button', { name: m.lane_red() })).toBeNull();
		// No lane goes to the API, even from an older link.
		expect(calls(api).find((call) => call.startsWith('GET /api/v1/documents'))).not.toContain(
			'lane'
		);
	});

	it('takes no lane from an older link', async () => {
		state.url = new URL('http://papiq/ui/documents?lane=yellow');
		const api = fakeApi({
			'GET /api/v1/documents': () => ({ items: [], next_cursor: null })
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		expect(await screen.findByText(m.documents_none())).toBeTruthy();
		const listed = calls(api).filter((call) => call.startsWith('GET /api/v1/documents'));
		expect(listed.length).toBeGreaterThan(0);
		expect(listed.every((call) => !call.includes('lane'))).toBe(true);
	});
});
