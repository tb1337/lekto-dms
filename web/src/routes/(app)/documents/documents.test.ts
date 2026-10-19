import { render, screen, within } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatDate } from '#lib/i18n.ts';
import { rememberView } from '#lib/listing.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi, listedOf, OWNER } from '#lib/testing/documents.ts';
import Page from './+page.svelte';

const state = vi.hoisted(() => ({ url: new URL('http://lekto/ui/documents') }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', () => ({
	page: {
		get url() {
			return state.url;
		}
	}
}));

beforeEach(() => {
	state.url = new URL('http://lekto/ui/documents');
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

	it('stands the documents by month while sorted by a date, last those without one', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/documents': () => ({
					items: [
						listedOf({ id: 'd1', title: 'Strom', document_date: '2026-10-01' }),
						listedOf({ id: 'd2', title: 'Lohn', document_date: '2026-09-30' }),
						listedOf({ id: 'd3', title: 'Lose', document_date: null })
					],
					next_cursor: null
				})
			})
		);
		render(Page);
		await screen.findByText('Strom');
		const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent?.trim());
		expect(headings).toEqual([
			formatDate(new Date(2026, 9, 1), { month: 'long', year: 'numeric' }),
			formatDate(new Date(2026, 8, 1), { month: 'long', year: 'numeric' }),
			m.documents_no_date()
		]);
		const october = screen.getByRole('region', { name: headings[0] });
		expect(within(october).getByText('Strom')).toBeTruthy();
		expect(within(october).queryByText('Lohn')).toBeNull();
	});

	it('stands the documents without headings while sorted by title', async () => {
		state.url = new URL('http://lekto/ui/documents?sort=title');
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/documents': () => ({
					items: [listedOf({ id: 'd1', title: 'Strom', document_date: '2026-10-01' })],
					next_cursor: null
				})
			})
		);
		render(Page);
		await screen.findByText('Strom');
		expect(screen.queryAllByRole('heading', { level: 2 })).toEqual([]);
	});

	it('counts the documents of the filters, and asks with each chosen contact', async () => {
		state.url = new URL('http://lekto/ui/documents?contact=c1&contact=c2&date_from=2026-01-01');
		const api = fakeApi({
			'GET /api/v1/documents': () => ({
				items: [listedOf({ id: 'd1', title: 'Strom', document_date: '2026-10-01' })],
				next_cursor: null
			}),
			'GET /api/v1/documents/facets': () => ({
				total: 7,
				contacts: [],
				document_types: [],
				topics: [],
				tags: [],
				years: [],
				undated: 0
			})
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		expect(await screen.findByText(m.documents_total({ count: '7' }))).toBeTruthy();
		for (const path of ['/api/v1/documents?', '/api/v1/documents/facets?']) {
			const call = calls(api).find((entry) => entry.startsWith(`GET ${path}`))!;
			expect(call).toContain('contact_id=c1&contact_id=c2');
			expect(call).toContain('document_date_from=2026-01-01');
		}
	});

	it('takes no lane from an older link', async () => {
		state.url = new URL('http://lekto/ui/documents?lane=yellow');
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
