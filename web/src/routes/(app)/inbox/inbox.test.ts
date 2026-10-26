import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { inbox } from '#lib/inbox.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
import { session, type User } from '#lib/session.svelte.ts';
import { calls, fakeApi, inboxItem, json, OWNER, summaryOf } from '#lib/testing/documents.ts';
import { uploads } from '#lib/upload.svelte.ts';
import Page from './+page.svelte';

const state = vi.hoisted(() => ({ url: new URL('http://lekto/ui/inbox') }));
vi.mock('$app/navigation', () => ({ beforeNavigate: vi.fn(), goto: vi.fn() }));
vi.mock('$app/state', () => ({
	page: {
		get url() {
			return state.url;
		}
	}
}));

const USERS = [
	{ id: OWNER, username: 'tobi', role: 'user', active: true },
	{ id: 'admin-1', username: 'admin', role: 'admin', active: true }
];
const SPACES = [
	{
		id: 'space-1',
		name: 'Personal',
		personal_of: OWNER,
		role: 'edit',
		members: [{ user_id: OWNER, role: 'edit' }]
	},
	{
		id: 'space-2',
		name: 'Personal',
		personal_of: 'admin-1',
		role: 'edit',
		members: [{ user_id: 'admin-1', role: 'edit' }]
	},
	{
		id: 'space-house',
		name: 'Haushalt',
		personal_of: null,
		role: 'edit',
		members: [
			{ user_id: OWNER, role: 'edit', username: 'tobi', active: true },
			{ user_id: 'anna-1', role: 'read', username: 'anna', active: true }
		]
	}
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
		'POST /api/v1/inbox/seen': () => ({ marked: 2 }),
		'POST /api/v1/documents': () => json({ id: 'doc-new' }, 202),
		'GET /api/v1/spaces': () => SPACES
	});
	vi.stubGlobal('fetch', api);
	inbox.summary = summary;
	render(Page);
	return api;
}

function signIn(role: User['role'] = 'user') {
	session.start({
		user:
			role === 'admin'
				? { id: 'admin-1', username: 'admin', role }
				: { id: OWNER, username: 'tobi', role },
		method: 'password',
		expires_at: '2026-10-18T12:00:00Z',
		csrf_token: 'token'
	});
}

beforeEach(() => {
	state.url = new URL('http://lekto/ui/inbox');
	phone.override(false);
	signIn();
});

afterEach(() => {
	inbox.summary = null;
	uploads.reset();
	phone.override(null);
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
		state.url = new URL('http://lekto/ui/inbox?tab=intervene');
		const api = start([inboxItem('intervene')], summaryOf({ intervene: 1 }));
		await screen.findByText(m.lane_red());
		expect(calls(api)).toContain('GET /api/v1/inbox?tab=intervene');
		const current = tabs().getByRole('link', { current: 'page' });
		expect(current.getAttribute('href')).toBe('/ui/inbox?tab=intervene');
	});

	it('takes an unknown tab for everything open', async () => {
		state.url = new URL('http://lekto/ui/inbox?tab=bogus');
		const api = start([]);
		await screen.findByText(m.inbox_empty());
		expect(calls(api)).toContain('GET /api/v1/inbox');
		expect(calls(api).some((call) => call.includes('tab='))).toBe(false);
	});

	it('says per tab that it is empty', async () => {
		state.url = new URL('http://lekto/ui/inbox?tab=done');
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

	it('names the space Lekto suggests, and who would see the document there', async () => {
		start([
			inboxItem(
				'review',
				{ id: 'y2', title: 'Vorschlag' },
				{
					open: [
						{
							node: 'judge',
							outcome: 'uncertain',
							reason: 'space: suggests another space, which shows it to more people',
							fields: [
								{
									field: 'space',
									outcome: 'uncertain',
									confidence: 0.89,
									reason: 'suggests another space, which shows it to more people',
									proposed: null,
									evidence: null,
									value: null,
									suggestion: 'space-house',
									new_name: null
								}
							]
						}
					]
				}
			)
		]);
		const row = (await screen.findByText('Vorschlag')).closest('li')!;
		expect(
			await within(row).findByText(m.space_suggestion_for({ space: 'Haushalt', names: 'anna' }))
		).toBeTruthy();
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
		state.url = new URL('http://lekto/ui/inbox?tab=done');
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

	it('starts done over after "mark as new", not on with the old cursor', async () => {
		state.url = new URL('http://lekto/ui/inbox?tab=done');
		let renewed = false;
		const api = fakeApi({
			'GET /api/v1/inbox': (_, url) => {
				const cursor = url.searchParams.get('cursor');
				if (renewed)
					return { items: [inboxItem('done', { id: 'c1', title: 'Zwei' })], next_cursor: null };
				return cursor
					? { items: [inboxItem('done', { id: 'c1', title: 'Zwei' })], next_cursor: null }
					: { items: [inboxItem('done', { id: 's1', title: 'Eins' })], next_cursor: 's1' };
			},
			'GET /api/v1/inbox/summary': () => summaryOf({ done: 2 }),
			'DELETE /api/v1/documents/s1/seen': () => {
				renewed = true;
				return new Response(null, { status: 204 });
			}
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		const row = (await screen.findByText('Eins')).closest('li')!;
		await userEvent.click(within(row).getByRole('button', { name: m.inbox_unseen() }));
		await screen.findByText('Zwei');
		const after = calls(api).slice(calls(api).indexOf('DELETE /api/v1/documents/s1/seen'));
		expect(after).toContain('GET /api/v1/inbox?tab=done');
		expect(after.some((call) => call.includes('cursor='))).toBe(false);
		expect(screen.queryByRole('button', { name: m.load_more() })).toBeNull();
	});

	it('starts over when the next page no longer follows', async () => {
		state.url = new URL('http://lekto/ui/inbox?tab=done');
		let pages = 0;
		const api = fakeApi({
			'GET /api/v1/inbox': (_, url) => {
				if (url.searchParams.get('cursor')) {
					return json({ type: 'about:blank', title: 'Unprocessable', status: 422 }, 422);
				}
				pages++;
				return pages === 1
					? { items: [inboxItem('done', { id: 'gone', title: 'Weg' })], next_cursor: 'gone' }
					: { items: [inboxItem('done', { id: 'c1', title: 'Da' })], next_cursor: null };
			},
			'GET /api/v1/inbox/summary': () => summaryOf({ done: 1 })
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		await screen.findByText('Weg');
		await userEvent.click(screen.getByRole('button', { name: m.load_more() }));
		expect(await screen.findByText('Da')).toBeTruthy();
		expect(screen.queryByRole('alert')).toBeNull();
		expect(calls(api).filter((call) => call === 'GET /api/v1/inbox?tab=done')).toHaveLength(2);
	});
});

const pdf = (name: string) => new File(['%PDF-1.7'], name, { type: 'application/pdf' });

function fileEntry(path: string, file: File) {
	return {
		isFile: true,
		isDirectory: false,
		name: file.name,
		fullPath: path,
		file: (resolve: (file: File) => void) => resolve(file)
	};
}

/** What a browser hands over for a drop of a folder `Scans` (a PDF, a text file, a folder with
 * another PDF) and a PDF beside it. */
function droppedFolder() {
	const inner = [fileEntry('/Scans/2026/b.pdf', pdf('b.pdf'))];
	const outer = [
		fileEntry('/Scans/a.pdf', pdf('a.pdf')),
		fileEntry('/Scans/notes.txt', new File(['hi'], 'notes.txt', { type: 'text/plain' })),
		{
			isFile: false,
			isDirectory: true,
			name: '2026',
			fullPath: '/Scans/2026',
			createReader: () => reader(inner)
		}
	];
	const reader = (entries: unknown[]) => {
		let done = false;
		return {
			readEntries(resolve: (entries: unknown[]) => void) {
				resolve(done ? [] : entries);
				done = true;
			}
		};
	};
	const roots = [
		{
			isFile: false,
			isDirectory: true,
			name: 'Scans',
			fullPath: '/Scans',
			createReader: () => reader(outer)
		},
		fileEntry('/c.pdf', pdf('c.pdf'))
	];
	return {
		types: ['Files'],
		items: roots.map((entry) => ({ kind: 'file', webkitGetAsEntry: () => entry })),
		files: [],
		dropEffect: 'none'
	};
}

describe('uploading in the inbox', () => {
	it('drops files and folders on the page into the personal space', async () => {
		const api = start([]);
		await screen.findByText(m.inbox_empty());
		expect(screen.queryByText(m.upload_drop_overlay())).toBeNull();
		await fireEvent.dragEnter(window, { dataTransfer: { types: ['Files'] } });
		expect(screen.getByText(m.upload_drop_overlay())).toBeTruthy();
		await fireEvent.drop(window, { dataTransfer: droppedFolder() });
		expect(screen.queryByText(m.upload_drop_overlay())).toBeNull();
		await waitFor(() =>
			expect(calls(api).filter((call) => call === 'POST /api/v1/documents')).toHaveLength(3)
		);
		const summary = await screen.findByRole('region', { name: m.upload_summary_label() });
		await waitFor(() =>
			expect(
				within(summary).getAllByText(
					`${m.upload_summary_uploaded({ count: 3 })}, ${m.upload_summary_skipped({ count: 1 })}`
				).length
			).toBeGreaterThan(0)
		);
		expect(within(summary).getByText('Scans/notes.txt')).toBeTruthy();
	});

	it('leaves the overlay when the files leave the page, and ignores other drags', async () => {
		start([]);
		await screen.findByText(m.inbox_empty());
		await fireEvent.dragEnter(window, { dataTransfer: { types: ['text/plain'] } });
		expect(screen.queryByText(m.upload_drop_overlay())).toBeNull();
		await fireEvent.dragEnter(window, { dataTransfer: { types: ['Files'] } });
		const overlay = screen.getByText(m.upload_drop_overlay()).closest('[role="presentation"]')!;
		await fireEvent.dragLeave(overlay);
		expect(screen.queryByText(m.upload_drop_overlay())).toBeNull();
	});

	it('offers no drop on a phone, only the button', async () => {
		phone.override(true);
		const api = start([]);
		await screen.findByText(m.inbox_empty());
		await fireEvent.dragEnter(window, { dataTransfer: { types: ['Files'] } });
		expect(screen.queryByText(m.upload_drop_overlay())).toBeNull();
		await fireEvent.drop(window, { dataTransfer: droppedFolder() });
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(calls(api)).not.toContain('POST /api/v1/documents');
		expect(screen.getByRole('button', { name: m.upload_title() })).toBeTruthy();
	});

	it('uploads with the dialog into the personal space, without asking for a space or owner', async () => {
		signIn('admin');
		const user = userEvent.setup();
		const append = vi.spyOn(FormData.prototype, 'append');
		try {
			const api = start([]);
			await screen.findByText(m.inbox_empty());
			await user.click(screen.getByRole('button', { name: m.upload_title() }));
			const dialog = await screen.findByRole('dialog');
			expect(within(dialog).queryByRole('combobox')).toBeNull();
			await user.upload(within(dialog).getByLabelText(m.upload_choose()), [pdf('a.pdf')]);
			await waitFor(() => expect(calls(api)).toContain('POST /api/v1/documents'));
			await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
			await waitFor(() => expect(document.body.style.pointerEvents).not.toBe('none'));
			expect(
				append.mock.calls.map(([name, value]) => [name, value instanceof File ? value.name : value])
			).toEqual([['file', 'a.pdf']]);
		} finally {
			append.mockRestore();
		}
	});
});
