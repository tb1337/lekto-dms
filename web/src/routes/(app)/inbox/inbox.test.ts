import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { inbox } from '#lib/inbox.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi, inboxItem, OWNER, summaryOf } from '#lib/testing/documents.ts';
import Page from './+page.svelte';

const state = vi.hoisted(() => ({ url: new URL('http://papiq/ui/inbox') }));
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', () => ({
	page: {
		get url() {
			return state.url;
		}
	}
}));

const USERS = [
	{ id: OWNER, username: 'tobi' },
	{ id: 'admin-1', username: 'admin' }
];

type Items = ReturnType<typeof inboxItem>[];

function start(items: Items | ((tab: string | null) => Items), summary = summaryOf({ new: 1 })) {
	const api = fakeApi({
		'GET /api/v1/inbox': (_, url) => ({
			items: typeof items === 'function' ? items(url.searchParams.get('tab')) : items,
			next_cursor: null
		}),
		'GET /api/v1/inbox/summary': () => summary,
		'GET /api/v1/users': () => USERS,
		'POST /api/v1/inbox/seen': () => ({ marked: 2 })
	});
	vi.stubGlobal('fetch', api);
	inbox.summary = summary;
	render(Page);
	return api;
}

beforeEach(() => {
	state.url = new URL('http://papiq/ui/inbox');
	session.start({
		user: { id: OWNER, username: 'tobi', role: 'user' },
		method: 'password',
		expires_at: '2026-10-18T12:00:00Z',
		csrf_token: 'token'
	});
});

afterEach(() => {
	inbox.summary = null;
	session.clear();
	vi.unstubAllGlobals();
});

function tabs() {
	return within(screen.getByRole('navigation', { name: m.inbox_tabs_label() }));
}

describe('inbox tabs', () => {
	it('lists everything open without a tab, and links each tab', async () => {
		const api = start([inboxItem('review')], summaryOf({ review: 1, new: 2, done: 4 }));
		await screen.findByText(m.lane_yellow());
		expect(calls(api)).toContain('GET /api/v1/inbox');
		const links = tabs().getAllByRole('link');
		expect(links.map((link) => link.getAttribute('href'))).toEqual([
			'/ui/inbox',
			'/ui/inbox?tab=new',
			'/ui/inbox?tab=review',
			'/ui/inbox?tab=intervene',
			'/ui/inbox?tab=processing',
			'/ui/inbox?tab=done'
		]);
		expect(links[0].getAttribute('aria-current')).toBe('page');
		// The counts of the summary; none for an empty tab.
		expect(links[0].textContent).toContain('3');
		expect(links[5].textContent).toContain('4');
		expect(links[3].textContent?.trim()).toBe(m.inbox_intervene());
	});

	it('shows the tab of the URL', async () => {
		state.url = new URL('http://papiq/ui/inbox?tab=intervene');
		const api = start([inboxItem('intervene')], summaryOf({ intervene: 1 }));
		await screen.findByText(m.lane_red());
		expect(calls(api)).toContain('GET /api/v1/inbox?tab=intervene');
		const current = tabs().getByRole('link', { current: 'page' });
		expect(current.getAttribute('href')).toBe('/ui/inbox?tab=intervene');
	});

	it('takes an unknown tab for everything open', async () => {
		state.url = new URL('http://papiq/ui/inbox?tab=bogus');
		const api = start([]);
		await screen.findByText(m.inbox_empty());
		expect(calls(api)).toContain('GET /api/v1/inbox');
		expect(calls(api).some((call) => call.includes('tab='))).toBe(false);
	});

	it('says per tab that it is empty', async () => {
		state.url = new URL('http://papiq/ui/inbox?tab=done');
		start([]);
		expect(await screen.findByText(m.inbox_empty_done())).toBeTruthy();
	});
});

describe('inbox rows', () => {
	it('shows the progress of a document in processing and why one waits', async () => {
		start([
			inboxItem('processing', { id: 'p1', title: 'Läuft noch' }),
			inboxItem(
				'review',
				{ id: 'y1', title: 'Gelb' },
				{
					open: [{ node: 'judge', outcome: 'uncertain', reason: 'Kontakt unsicher', fields: [] }]
				}
			)
		]);
		const running = (await screen.findByText('Läuft noch')).closest('li')!;
		expect(within(running).getByRole('progressbar')).toBeTruthy();
		const yellow = screen.getByText('Gelb').closest('li')!;
		expect(within(yellow).getByText(m.lane_yellow())).toBeTruthy();
		expect(within(yellow).getByText('Kontakt unsicher')).toBeTruthy();
		expect(within(yellow).queryByRole('button')).toBeNull();
		expect(within(running).getByRole('link').getAttribute('href')).toBe(
			'/ui/documents/p1?from=inbox'
		);
	});

	it('marks a new document calmly, with "seen" in its row', async () => {
		const api = start([inboxItem('new', { id: 'n1', title: 'Neu da' })]);
		const row = (await screen.findByText('Neu da')).closest('li')!;
		expect(within(row).getByText(m.inbox_new())).toBeTruthy();
		expect(row.querySelector('[data-lane]')).toBeNull();
		await userEvent.click(within(row).getByRole('button', { name: m.inbox_seen() }));
		await waitFor(() => expect(calls(api)).toContain('PUT /api/v1/documents/n1/seen'));
		// Afterwards the list and the counts are fetched again.
		await waitFor(() =>
			expect(calls(api).filter((call) => call === 'GET /api/v1/inbox/summary')).toHaveLength(1)
		);
		expect(calls(api).filter((call) => call === 'GET /api/v1/inbox').length).toBeGreaterThan(1);
	});

	it('asks before it marks everything new as seen', async () => {
		const user = userEvent.setup();
		const api = start([inboxItem('new'), inboxItem('new', { id: 'doc-2' })], summaryOf({ new: 2 }));
		await screen.findAllByText(m.inbox_new());
		await user.click(screen.getByRole('button', { name: m.inbox_all_seen() }));
		const dialog = await screen.findByRole('alertdialog');
		expect(dialog.textContent).toContain(m.inbox_all_seen_text({ count: 2 }));
		await user.click(within(dialog).getByRole('button', { name: m.cancel() }));
		expect(calls(api).some((call) => call.startsWith('POST'))).toBe(false);
		// bits-ui gives the page its pointer back once the dialog is gone.
		await waitFor(() => expect(document.body.style.pointerEvents).not.toBe('none'));

		await user.click(screen.getByRole('button', { name: m.inbox_all_seen() }));
		const again = await screen.findByRole('alertdialog');
		await user.click(within(again).getByRole('button', { name: m.inbox_all_seen_confirm() }));
		await waitFor(() => expect(calls(api)).toContain('POST /api/v1/inbox/seen'));
		await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
		await waitFor(() => expect(document.body.style.pointerEvents).not.toBe('none'));
	});

	it('offers "mark all as seen" only while something is new', async () => {
		start([inboxItem('review')], summaryOf({ review: 1 }));
		await screen.findByText(m.lane_yellow());
		expect(screen.queryByRole('button', { name: m.inbox_all_seen() })).toBeNull();
	});

	it('tells how, when and by whom a document left, and offers a seen one as new again', async () => {
		state.url = new URL('http://papiq/ui/inbox?tab=done');
		const api = start(
			[
				inboxItem('done', { id: 's1', title: 'Gesehen' }),
				inboxItem(
					'done',
					{ id: 'c1', title: 'Bestätigt' },
					{ done: { how: 'confirmed', at: '2026-10-18T10:00:00Z', by: 'admin-1' } }
				)
			],
			summaryOf({ done: 2 })
		);
		const seen = (await screen.findByText('Gesehen')).closest('li')!;
		const confirmed = screen.getByText('Bestätigt').closest('li')!;
		await waitFor(() =>
			expect(
				within(confirmed).getByText(
					new RegExp(`^${m.inbox_done_confirmed({ who: 'admin', when: '.+' })}$`)
				)
			).toBeTruthy()
		);
		expect(
			within(seen).getByText(
				new RegExp(`^${m.inbox_done_seen({ who: m.inbox_by_you(), when: '.+' })}$`)
			)
		).toBeTruthy();
		expect(within(confirmed).queryByRole('button')).toBeNull();
		await userEvent.click(within(seen).getByRole('button', { name: m.inbox_unseen() }));
		await waitFor(() => expect(calls(api)).toContain('DELETE /api/v1/documents/s1/seen'));
	});
});
