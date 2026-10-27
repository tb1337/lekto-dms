// The tab "Search index": the share of documents in the index and with vectors, what is open,
// the durations, and the check of admins; without embeddings nothing of the meaning.
import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { formatDuration } from '#lib/duration.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi, json } from '#lib/testing/documents.ts';
import SearchTab from './SearchTab.svelte';

const status = {
	documents: 3987,
	index: { documents: 3912, embedded: 3870, vectors: 20311, indexing: true, size_bytes: 412000000 },
	running: 1,
	queued: 74,
	remaining_ms: 240000,
	embedded_jobs: { count: 412, median_ms: 1800, p90_ms: 4200 },
	plain_jobs: { count: 1930, median_ms: 150, p90_ms: 400 },
	per_section_ms: 340,
	model: 'snowflake-arctic-embed2',
	dimensions: 1024,
	since: '2026-10-17T12:00:00Z'
};

function signIn(role: 'admin' | 'user') {
	session.start({
		user: { id: role, username: role, role },
		method: 'password',
		expires_at: '2026-10-25T12:00:00Z',
		csrf_token: 'token'
	});
}

beforeEach(() => signIn('admin'));

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
});

describe('the search index tab', () => {
	it('shows the shares, what is open and how long an indexing takes', async () => {
		vi.stubGlobal('fetch', fakeApi({ 'GET /api/v1/search/status': () => status }));
		render(SearchTab);
		expect(await screen.findByText(m.search_writing())).toBeTruthy();
		const bars = screen.getAllByRole('progressbar');
		expect(bars.map((bar) => bar.getAttribute('aria-valuenow'))).toEqual(['98', '99']);
		expect(screen.getByText('snowflake-arctic-embed2')).toBeTruthy();
		expect(screen.getByText(m.search_with_embedding())).toBeTruthy();
		expect(
			screen.getByText(m.search_open_done_in({ duration: formatDuration(240) }).replace(/\s/g, ' '))
		).toBeTruthy();
	});

	it('shows nothing of the meaning without embeddings', async () => {
		const plain = { ...status, model: null, dimensions: null, embedded_jobs: null };
		vi.stubGlobal('fetch', fakeApi({ 'GET /api/v1/search/status': () => plain }));
		render(SearchTab);
		expect(await screen.findByText(m.search_in_index())).toBeTruthy();
		expect(screen.queryByText(m.search_meaning())).toBeNull();
		expect(screen.queryByText(m.search_with_embedding())).toBeNull();
		expect(screen.getAllByRole('progressbar')).toHaveLength(1);
	});

	it('lets an admin check the index, a user not', async () => {
		const api = fakeApi({
			'GET /api/v1/search/status': () => status,
			'POST /api/v1/search/check': () => ({
				current: 3900,
				missing: 0,
				outdated: 3,
				other_model: 9,
				extra: 0,
				took_ms: 3400
			})
		});
		vi.stubGlobal('fetch', api);
		const { unmount } = render(SearchTab);
		await userEvent.click(await screen.findByRole('button', { name: m.search_check_button() }));
		expect(await screen.findByText(m.search_check_other_model())).toBeTruthy();
		expect(screen.getByText(m.search_check_missing())).toBeTruthy();
		expect(screen.queryByText(m.search_check_extra())).toBeNull();
		expect(calls(api)).toContain('POST /api/v1/search/check');
		unmount();

		signIn('user');
		render(SearchTab);
		expect(await screen.findByText(m.search_in_index())).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.search_check_button() })).toBeNull();
	});

	it('lets an admin rebuild the index after a question, a user not', async () => {
		const api = fakeApi({
			'GET /api/v1/search/status': () => ({
				...status,
				index: { ...status.index, indexing: false }
			}),
			'POST /api/v1/search/reindex': () => new Response(null, { status: 202 })
		});
		vi.stubGlobal('fetch', api);
		const { unmount } = render(SearchTab);
		await userEvent.click(await screen.findByRole('button', { name: m.search_reindex_button() }));
		const dialog = await screen.findByRole('alertdialog');
		expect(dialog.textContent).toContain(m.search_reindex_confirm_text());
		expect(calls(api)).not.toContain('POST /api/v1/search/reindex');
		await userEvent.click(within(dialog).getByRole('button', { name: m.search_reindex_button() }));
		await waitFor(() => expect(calls(api)).toContain('POST /api/v1/search/reindex'));
		unmount();

		signIn('user');
		render(SearchTab);
		expect(await screen.findByText(m.search_in_index())).toBeTruthy();
		expect(screen.queryByRole('button', { name: m.search_reindex_button() })).toBeNull();
	});

	it('says so when the installation has no search', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/search/status': () =>
					json(
						{
							type: 'about:blank',
							title: 'Unavailable',
							status: 503,
							detail: 'no search',
							reason: { code: 'search_not_configured', params: {} }
						},
						503
					)
			})
		);
		render(SearchTab);
		expect(await screen.findByText(m.reason_search_not_configured())).toBeTruthy();
	});
});
