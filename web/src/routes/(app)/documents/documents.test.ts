import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { goto } from '$app/navigation';
import { POLL } from '#lib/bulk.svelte.ts';
import { usageLabel } from '#lib/components/UsageCount.svelte';
import { events } from '#lib/events.svelte.ts';
import { formatDate } from '#lib/i18n.ts';
import { forgetMeaningSearch } from '#lib/meaning-search.ts';
import {
	filtersCollapsed,
	rememberFilters,
	rememberFiltersCollapsed,
	rememberLayout,
	rememberedFilters
} from '#lib/listing.ts';
import { NO_FILTERS } from '#lib/filters.ts';
import { formatNumber } from '#lib/i18n.ts';
import { m } from '#lib/paraglide/messages.js';
import { session } from '#lib/session.svelte.ts';
import { calls, fakeApi, listedOf, OWNER } from '#lib/testing/documents.ts';
import Page from './+page.svelte';

class FakeSource {
	static last: FakeSource;
	onopen: (() => void) | null = null;
	onerror: (() => void) | null = null;
	readyState = 1;
	listeners = new Map<string, (message: { data: string }) => void>();
	constructor(readonly url: string) {
		FakeSource.last = this;
	}
	addEventListener(type: string, handler: (message: { data: string }) => void) {
		this.listeners.set(type, handler);
	}
	close() {
		this.readyState = 2;
	}
}

const state = vi.hoisted(() => ({
	url: new URL('http://lekto/ui/documents'),
	// The history entry: the words of a search stand here, never in the URL.
	entry: {} as App.PageState
}));
vi.mock('$app/navigation', () => ({ beforeNavigate: vi.fn(), goto: vi.fn() }));
vi.mock('$app/state', () => ({
	page: {
		get url() {
			return state.url;
		},
		get state() {
			return state.entry;
		}
	}
}));

/** The options of a navigation of the list that searches for `words`. */
const searching = (words: string, options: object = { reset: false }) => ({
	...options,
	state: { words },
	persistState: true
});

beforeEach(() => {
	forgetMeaningSearch();
	state.url = new URL('http://lekto/ui/documents');
	state.entry = {};
	session.start({
		user: { id: OWNER, username: 'tobi', role: 'user' },
		method: 'password',
		expires_at: '2026-10-18T12:00:00Z',
		csrf_token: 'token'
	});
	// Rows: their mark stands beside their link (the grid's is tested with the card).
	rememberLayout('list');
});

afterEach(() => {
	localStorage.clear();
	session.clear();
	vi.unstubAllGlobals();
	vi.useRealTimers();
	// A menu open while the clock was faked leaves this behind.
	window.document.body.style.pointerEvents = '';
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
			'/ui/documents/d1?from=inbox'
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

	it('opens a document in the Beam, paging through the documents of the page', async () => {
		state.entry = { words: '' };
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/documents': () => ({
					items: [listedOf({ id: 'd1', title: 'Eins' }), listedOf({ id: 'd2', title: 'Zwei' })],
					next_cursor: null
				})
			})
		);
		const user = userEvent.setup();
		render(Page);
		await screen.findByText('Zwei');
		await user.click(screen.getByRole('button', { name: m.beam_open_named({ title: 'Zwei' }) }));
		expect(goto).toHaveBeenLastCalledWith('http://lekto/ui/documents', {
			shallow: true,
			state: { words: '', beam: { ids: ['d1', 'd2'], index: 1, from: m.nav_documents() } },
			persistState: true
		});
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
		// The list's headings, not those of the filters beside it.
		const listHeadings = () =>
			screen.queryAllByRole('heading', { level: 2 }).filter((h) => !h.closest('aside'));
		const headings = listHeadings().map((h) => h.textContent?.trim());
		expect(headings).toEqual([
			formatDate(new Date(2026, 9, 1), { month: 'long', year: 'numeric' }),
			formatDate(new Date(2026, 8, 1), { month: 'long', year: 'numeric' }),
			m.documents_no_date()
		]);
		const october = screen.getByRole('region', { name: headings[0] });
		expect(within(october).getByText('Strom')).toBeTruthy();
		expect(within(october).queryByText('Lohn')).toBeNull();
	});

	it('shows one page of 50 at a time, the page in the link', async () => {
		state.url = new URL('http://lekto/ui/documents?sort=title&page=2');
		const api = fakeApi({
			'GET /api/v1/documents': () => ({
				items: [listedOf({ id: 'd51', title: 'Strom', document_date: '2026-10-01' })],
				next_cursor: null
			}),
			'GET /api/v1/documents/count': () => ({ total: 120 })
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		await screen.findByText('Strom');
		const listed = calls(api).filter((call) => call.startsWith('GET /api/v1/documents?'));
		expect(listed.at(-1)).toContain('offset=50');
		expect(listed.at(-1)).toContain('limit=50');
		const pages = screen.getByRole('navigation', { name: m.pagination_label() });
		await userEvent.click(
			within(pages).getByRole('button', { name: m.pagination_page({ page: '3' }) })
		);
		expect(goto).toHaveBeenLastCalledWith('?sort=title&page=3', searching('', { replace: false }));
	});

	it('loads the page shown again after a reconnect of the event stream, not the first', async () => {
		state.url = new URL('http://lekto/ui/documents?sort=title&page=2');
		const api = fakeApi({
			'GET /api/v1/documents': () => ({
				items: [listedOf({ id: 'd51', title: 'Strom', document_date: '2026-10-01' })],
				next_cursor: null
			}),
			'GET /api/v1/documents/count': () => ({ total: 120 })
		});
		vi.stubGlobal('fetch', api);
		events.useFactory((url) => new FakeSource(url) as unknown as EventSource);
		events.start(() => {});
		FakeSource.last.onopen?.();
		render(Page);
		await screen.findByText('Strom');
		const listed = () => calls(api).filter((call) => call.startsWith('GET /api/v1/documents?'));
		expect(listed()).toHaveLength(1);
		// The stream opens again after a break: the data shown may be stale.
		FakeSource.last.onopen?.();
		await vi.waitFor(() => expect(listed()).toHaveLength(2));
		expect(listed().at(-1)).toContain('offset=50');
		expect(goto).not.toHaveBeenCalled();
		events.stop();
	});

	// Opens two menus and a dialog and follows a poll: the longest test of the page, longer
	// while every worker runs one beside it.
	it('chooses in the selection mode: the page, then every hit, and confirms them all', async () => {
		// The clock is faked so the poll that follows the action comes at once.
		vi.useFakeTimers({ shouldAdvanceTime: true });
		const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
		const sent: unknown[] = [];
		const operation = {
			id: 'op-1',
			kind: 'confirm',
			status: 'queued',
			total: 120,
			done: 0,
			changed: 0,
			unchanged: 0,
			skipped: [],
			error: null,
			created_at: '2026-10-29T12:00:00Z',
			finished_at: null
		};
		const api = fakeApi({
			'GET /api/v1/documents': () => ({
				items: [listedOf({ id: 'd1', title: 'Strom' }), listedOf({ id: 'd2', title: 'Gas' })],
				next_cursor: null
			}),
			'GET /api/v1/documents/count': () => ({ total: 120 }),
			'POST /api/v1/documents/bulk': async (request, url) => {
				sent.push({ query: url.search, body: await request.json() });
				return operation;
			},
			'GET /api/v1/documents/bulk/op-1': () => ({
				...operation,
				status: 'done',
				done: 120,
				changed: 118,
				unchanged: 2
			})
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		await screen.findByText('Strom');
		// Outside the mode: no boxes, no bar, the cards are links.
		expect(
			screen.queryByRole('checkbox', { name: m.bulk_select_document({ title: 'Gas' }) })
		).toBeNull();
		const mode = screen.getAllByRole('button', { name: m.bulk_mode() })[0];
		await user.click(mode);
		expect(mode.getAttribute('aria-pressed')).toBe('true');
		const empty = screen.getByRole('region', { name: m.selection_selected({ count: '0' }) });
		expect(empty.textContent).toContain(m.bulk_tap_hint());
		expect(
			within(empty).getByRole('button', { name: m.field_tags() }).hasAttribute('disabled')
		).toBe(true);

		const choose = async (item: string) => {
			const bar = screen.getByRole('region', { name: /ausgewählt|selected/ });
			const chooser = within(bar).getByRole('button', { name: m.bulk_mode() });
			await fireEvent.pointerDown(chooser, { button: 0, pointerType: 'mouse' });
			await user.click(await screen.findByRole('menuitem', { name: item }));
		};
		await choose(m.bulk_select_page());
		screen.getByRole('region', { name: m.selection_selected({ count: '2' }) });
		const gas = screen.getByRole('checkbox', { name: m.bulk_select_document({ title: 'Gas' }) });
		expect((gas as HTMLInputElement).checked).toBe(true);
		await choose(m.bulk_select_all({ count: formatNumber(120) }));
		const all = screen.getByRole('region', {
			name: m.selection_selected({ count: formatNumber(120) })
		});
		expect(all.textContent).toContain(m.bulk_all_hits());

		await fireEvent.pointerDown(within(all).getByRole('button', { name: m.bulk_more() }), {
			button: 0,
			pointerType: 'mouse'
		});
		await user.click(await screen.findByRole('menuitem', { name: m.bulk_confirm() }));
		await vi.waitFor(() => expect(sent).toHaveLength(1));
		expect(sent[0]).toEqual({
			query: '',
			body: { document_ids: null, action: { kind: 'confirm' } }
		});
		// The bar follows the action until it ends; then the choice is let go.
		await vi.advanceTimersByTimeAsync(POLL);
		await vi.waitFor(() =>
			expect(
				screen.queryByRole('region', { name: m.selection_selected({ count: formatNumber(120) }) })
			).toBeNull()
		);
		// The mode stays: nothing chosen any more.
		screen.getByRole('region', { name: m.selection_selected({ count: '0' }) });
		await choose(m.bulk_mode_end());
		expect(screen.queryByRole('region', { name: m.selection_selected({ count: '0' }) })).toBeNull();
		expect(
			screen.queryByRole('checkbox', { name: m.bulk_select_document({ title: 'Gas' }) })
		).toBeNull();
	}, 15_000);

	it('chooses a document by a tap on it, and deletes after asking with the number', async () => {
		const sent: unknown[] = [];
		const api = fakeApi({
			'GET /api/v1/documents': () => ({
				items: [listedOf({ id: 'd1', title: 'Strom' }), listedOf({ id: 'd2', title: 'Gas' })],
				next_cursor: null
			}),
			'GET /api/v1/documents/count': () => ({ total: 2 }),
			'POST /api/v1/documents/bulk': async (request) => {
				sent.push(await request.json());
				return { id: 'op-2', status: 'queued', total: 1, done: 0, skipped: [] };
			}
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		await screen.findByText('Gas');
		await userEvent.click(screen.getAllByRole('button', { name: m.bulk_mode() })[0]);
		// In the mode the card is the label of its box: a tap on its title chooses it.
		await userEvent.click(screen.getByText('Gas'));
		const bar = screen.getByRole('region', { name: m.selection_selected({ count: '1' }) });
		await fireEvent.pointerDown(within(bar).getByRole('button', { name: m.bulk_more() }), {
			button: 0,
			pointerType: 'mouse'
		});
		await userEvent.click(await screen.findByRole('menuitem', { name: m.bulk_delete() }));
		const dialog = await screen.findByRole('alertdialog', {
			name: m.bulk_delete_title({ documents: usageLabel(1) })
		});
		await userEvent.click(within(dialog).getByRole('button', { name: m.delete_title() }));
		await vi.waitFor(() =>
			expect(sent).toEqual([{ document_ids: ['d2'], action: { kind: 'delete' } }])
		);
	});

	it('offers 25, 50 or 100 to a page, remembered for the documents alone', async () => {
		localStorage.setItem('lekto.page-size.jobs', '100');
		const api = fakeApi({
			'GET /api/v1/documents': () => ({
				items: [listedOf({ id: 'd1', title: 'Strom', document_date: '2026-10-01' })],
				next_cursor: null
			}),
			'GET /api/v1/documents/count': () => ({ total: 120 })
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		await screen.findByText('Strom');
		const listed = () => calls(api).filter((call) => call.startsWith('GET /api/v1/documents?'));
		expect(listed().at(-1)).toContain('limit=50');
		const size = screen.getByRole('button', { name: m.pagination_size({ size: '50' }) });
		await fireEvent.pointerDown(size, { button: 0, pointerType: 'mouse' });
		await userEvent.click(
			await screen.findByRole('menuitemradio', { name: m.pagination_size({ size: '25' }) })
		);
		await vi.waitFor(() => expect(listed().at(-1)).toContain('limit=25'));
		expect(localStorage.getItem('lekto.page-size.documents')).toBe('25');
		expect(localStorage.getItem('lekto.page-size.jobs')).toBe('100');
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
		expect(
			screen.queryAllByRole('heading', { level: 2 }).filter((h) => !h.closest('aside'))
		).toEqual([]);
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
				contact_groups: [],
				document_type_groups: [],
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

	it('keeps title and close of the filter sheet at the top, reset and show at the bottom', async () => {
		state.url = new URL('http://lekto/ui/documents?contact=c1');
		const api = fakeApi({
			'GET /api/v1/documents': () => ({ items: [], next_cursor: null }),
			'GET /api/v1/documents/facets': () => ({
				total: 3,
				contacts: [],
				document_types: [],
				contact_groups: [],
				document_type_groups: [],
				topics: [],
				tags: [],
				years: [],
				undated: 0
			})
		});
		vi.stubGlobal('fetch', api);
		const user = userEvent.setup();
		render(Page);
		await screen.findByText(m.documents_total({ count: '3' }));
		await user.click(screen.getByRole('button', { name: m.filters_open() }));
		const sheet = await screen.findByRole('dialog', { name: m.filters_title() });
		const close = within(sheet).getAllByRole('button', { name: m.close() });
		expect(close).toHaveLength(1);
		const show = within(sheet).getByRole('button', { name: m.filters_show({ count: '3' }) });
		expect(within(sheet).getByRole('button', { name: m.filters_reset() })).toBeTruthy();
		await user.click(show);
		expect(screen.queryByRole('dialog', { name: m.filters_title() })).toBeNull();
	});

	it('opens a lens: its name as title, its sort by a field asked of the API', async () => {
		state.url = new URL('http://lekto/ui/documents?lens=l1&tag=t1&sort=field&sort_field=f1');
		const lens = (id: string, name: string) => ({
			id,
			name,
			position: 0,
			filter: {},
			query: null,
			sort: null,
			sort_field_id: null,
			grouping: 'none',
			layout: 'grid',
			card_field_ids: [],
			due_field_id: null,
			created_at: '2026-10-20T10:00:00Z',
			updated_at: '2026-10-20T10:00:00Z'
		});
		const api = fakeApi({
			'GET /api/v1/documents': () => ({ items: [], next_cursor: null }),
			'GET /api/v1/lenses': () => [lens('l1', 'Zu bezahlen'), lens('l2', 'Steuer')]
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		expect(await screen.findByRole('heading', { level: 1, name: 'Zu bezahlen' })).toBeTruthy();
		const listed = calls(api).filter((call) => call.startsWith('GET /api/v1/documents?'));
		expect(listed.at(-1)).toContain('sort=field');
		expect(listed.at(-1)).toContain('sort_field_id=f1');
		// Each lens is a link that opens it (beside the list and, on a phone, as a chip).
		const tax = screen.getAllByRole('link', { name: 'Steuer' });
		expect(tax.map((link) => link.getAttribute('href'))).toEqual(['?lens=l2', '?lens=l2']);
		const open = screen.getAllByRole('link', { name: 'Zu bezahlen' });
		expect(open.every((link) => link.getAttribute('aria-current') === 'page')).toBe(true);
		const all = screen.getAllByRole('link', { name: m.lens_all() });
		expect(all[0].getAttribute('href')).toBe('/ui/documents');
	});

	it('shows how many documents each lens and all documents show', async () => {
		state.url = new URL('http://lekto/ui/documents');
		const lens = (id: string, name: string, query: string | null = null) => ({
			id,
			name,
			position: 0,
			filter: id === 'l1' ? { tag_ids: ['t1'] } : {},
			query,
			sort: null,
			sort_field_id: null,
			grouping: 'none',
			layout: 'grid',
			card_field_ids: [],
			due_field_id: null,
			created_at: '2026-10-20T10:00:00Z',
			updated_at: '2026-10-20T10:00:00Z'
		});
		const api = fakeApi({
			'GET /api/v1/documents': () => ({ items: [], next_cursor: null }),
			'GET /api/v1/lenses': () => [lens('l1', 'Zu bezahlen'), lens('l2', 'Strom', 'strom')],
			'GET /api/v1/documents/count': (_request, url) => ({
				total: url.searchParams.has('tag_id') ? 7 : 1234
			}),
			'POST /api/v1/documents/search': () => ({
				items: [],
				estimated_total: 12,
				next_offset: null,
				semantic: false
			})
		});
		vi.stubGlobal('fetch', api);
		render(Page);
		// Beside the list (the phone's chips show no numbers).
		const texts = (name: RegExp) =>
			screen.getAllByRole('link', { name }).map((link) => link.textContent ?? '');
		await vi.waitFor(() =>
			expect(texts(/Zu bezahlen/).some((text) => text.includes('7'))).toBe(true)
		);
		expect(texts(/Strom/).some((text) => text.includes('12'))).toBe(true);
		const all = new RegExp(m.lens_all());
		expect(texts(all).some((text) => text.includes(formatNumber(1234)))).toBe(true);
		// A lens with words counts by the words alone, without the embedding.
		const searched = calls(api).find((call) => call.startsWith('POST /api/v1/documents/search?'));
		expect(searched).toContain('semantic_ratio=0');
	});

	it('groups a lens by its deadline and shows its fields on the cards', async () => {
		state.url = new URL('http://lekto/ui/documents?lens=l1');
		const yesterday = new Date(Date.now() - 86_400_000);
		const due = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`;
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/documents': () => ({
					items: [
						listedOf({
							id: 'd1',
							title: 'Strom',
							fields: { f1: due, f2: { amount: '89.00', currency: 'EUR' } }
						}),
						listedOf({ id: 'd2', title: 'Brief' })
					],
					next_cursor: null
				}),
				'GET /api/v1/fields': () => [
					{ id: 'f1', name: 'Fällig am', data_type: 'date' },
					{ id: 'f2', name: 'Betrag', data_type: 'amount' }
				],
				'GET /api/v1/lenses': () => [
					{
						id: 'l1',
						name: 'Zu bezahlen',
						position: 0,
						filter: {},
						query: null,
						sort: null,
						sort_field_id: null,
						grouping: 'due',
						layout: 'grid',
						card_field_ids: ['f2', 'f1'],
						due_field_id: 'f1',
						created_at: '2026-10-20T10:00:00Z',
						updated_at: '2026-10-20T10:00:00Z'
					}
				]
			})
		);
		render(Page);
		const overdue = await screen.findByRole('region', { name: m.lens_group_overdue() });
		expect(within(overdue).getByText('Strom')).toBeTruthy();
		expect(within(overdue).getByText(m.due_overdue_one(), { exact: false })).toBeTruthy();
		expect(within(overdue).getByText(/89/)).toBeTruthy();
		const none = screen.getByRole('region', { name: m.lens_group_no_due() });
		expect(within(none).getByText('Brief')).toBeTruthy();
	});

	it('offers to keep in the lens what the page shows beyond it, or to go back', async () => {
		state.url = new URL('http://lekto/ui/documents?lens=l1&tag=t1&tag=t2');
		const lens = {
			id: 'l1',
			name: 'Zu bezahlen',
			position: 0,
			filter: { tag_ids: ['t1'] },
			query: null,
			sort: null,
			sort_field_id: null,
			grouping: 'none',
			layout: 'grid',
			card_field_ids: [],
			due_field_id: null,
			created_at: '2026-10-20T10:00:00Z',
			updated_at: '2026-10-20T10:00:00Z'
		};
		const patched: unknown[] = [];
		const api = fakeApi({
			'GET /api/v1/documents': () => ({ items: [], next_cursor: null }),
			'GET /api/v1/lenses': () => [lens],
			'PATCH /api/v1/lenses/l1': async (request) => {
				const body = await request.json();
				patched.push(body);
				return { ...lens, ...body };
			}
		});
		vi.stubGlobal('fetch', api);
		const user = userEvent.setup();
		render(Page);
		const keep = await screen.findByRole('button', {
			name: m.lens_save_into({ name: 'Zu bezahlen' })
		});
		expect(screen.getByText(m.lens_changed())).toBeTruthy();
		await user.click(keep);
		await vi.waitFor(() => expect(patched).toHaveLength(1));
		expect(patched[0]).toMatchObject({ filter: { tag_ids: ['t1', 't2'] }, query: null });
		await user.click(screen.getByRole('button', { name: m.lens_discard() }));
		expect(vi.mocked(goto)).toHaveBeenLastCalledWith('?lens=l1&tag=t1', searching(''));
	});

	it('shows the words of a search as a chip that ends it, their count by the title', async () => {
		state.url = new URL('http://lekto/ui/documents?tag=t1');
		state.entry = { words: 'Strom' };
		const bodies: unknown[] = [];
		const api = fakeApi({
			'POST /api/v1/documents/search': async (request) => {
				bodies.push(await request.json());
				return { items: [], estimated_total: 4, next_offset: null, semantic: false };
			}
		});
		vi.stubGlobal('fetch', api);
		const user = userEvent.setup();
		render(Page);
		expect(await screen.findByText(m.search_total({ count: '4' }))).toBeTruthy();
		// The words go in the body, never in an address; the filters stay query parameters.
		expect(bodies).toEqual([{ q: 'Strom' }]);
		const searched = calls(api).find((call) => call.startsWith('POST /api/v1/documents/search'));
		expect(searched).toContain('tag_id=t1');
		expect(searched).not.toContain('Strom');
		await user.click(
			screen.getByRole('button', { name: m.search_chip_remove({ words: 'Strom' }) })
		);
		expect(vi.mocked(goto)).toHaveBeenLastCalledWith('?tag=t1', searching(''));
	});

	it('says when a search went by words alone, and offers the meaning once it is ready', async () => {
		state.entry = { words: 'Weihnachten' };
		let first = true;
		const api = fakeApi({
			'GET /api/v1/pipeline': () => ({
				nodes: [],
				vision: null,
				logo_fetch: false,
				meaning_search: true
			}),
			'POST /api/v1/documents/search': () => {
				const pending = first;
				first = false;
				return {
					items: [listedOf({ id: 'd1', title: 'Kontoauszug Dezember' })].map((document) => ({
						document,
						score: 0.9,
						snippet: []
					})),
					estimated_total: 1,
					next_offset: null,
					semantic: !pending,
					mode: pending ? 'words' : 'hybrid',
					reason: pending ? { code: 'search_embed_timeout', params: { seconds: 5 } } : null,
					meaning_pending: pending
				};
			}
		});
		vi.stubGlobal('fetch', api);
		events.useFactory((url) => new FakeSource(url) as unknown as EventSource);
		events.start(() => {});
		const user = userEvent.setup();
		render(Page);
		expect(
			await screen.findByText(m.reason_search_embed_timeout({ seconds: '5' }), { exact: false })
		).toBeTruthy();
		expect(screen.getByText(m.search_meaning_pending(), { exact: false })).toBeTruthy();
		FakeSource.last.listeners.get('search.meaning_ready')?.({
			data: JSON.stringify({
				type: 'search.meaning_ready',
				id: 'e1',
				occurred_at: '',
				query: 'Weihnachten'
			})
		});
		await user.click(await screen.findByRole('button', { name: m.search_with_meaning() }));
		await vi.waitFor(() =>
			expect(
				screen.queryByText(m.reason_search_embed_timeout({ seconds: '5' }), { exact: false })
			).toBeNull()
		);
		const searches = calls(api).filter((call) => call.startsWith('POST /api/v1/documents/search'));
		expect(searches[0]).not.toContain('semantic_ratio');
		expect(searches.at(-1)).not.toContain('semantic_ratio');
		events.stop();
	});

	it('shows nothing of the meaning where the installation has no search by it', async () => {
		state.entry = { words: 'Strom' };
		const api = fakeApi({
			'GET /api/v1/pipeline': () => ({
				nodes: [],
				vision: null,
				logo_fetch: false,
				meaning_search: false
			}),
			'POST /api/v1/documents/search': () => ({
				items: [],
				estimated_total: 0,
				next_offset: null,
				semantic: false,
				mode: 'words',
				reason: { code: 'search_no_embeddings', params: {} },
				meaning_pending: false
			})
		});
		vi.stubGlobal('fetch', api);
		const user = userEvent.setup();
		render(Page);
		expect(await screen.findByText(m.search_none())).toBeTruthy();
		const [field] = screen.getAllByRole('searchbox', { name: m.documents_search_label() });
		await user.type(field, 'x');
		await new Promise((resolve) => setTimeout(resolve, 20));
		expect(screen.queryByText(m.reason_search_no_embeddings(), { exact: false })).toBeNull();
		expect(calls(api).some((call) => call.includes('/search/warm'))).toBe(false);
	});

	it('applies the filters this browser last set when opened without any', async () => {
		rememberFilters({ ...NO_FILTERS, contacts: ['c1'], tags: ['t1'] });
		vi.stubGlobal('fetch', fakeApi());
		render(Page);
		expect(vi.mocked(goto)).toHaveBeenCalledWith(
			'?contact=c1&tag=t1',
			searching('', { replace: true, reset: false })
		);
	});

	it.each([
		// A link's filters show, and are remembered in turn; words and a lens leave the memory.
		['?tag=t2', {}, { ...NO_FILTERS, tags: ['t2'] }],
		['?contact=c2&layout=stream', {}, { ...NO_FILTERS, contacts: ['c2'] }],
		['', { words: 'Strom' }, { ...NO_FILTERS, contacts: ['c1'] }],
		['?lens=l1', {}, { ...NO_FILTERS, contacts: ['c1'] }],
		['?lens=l1&tag=t2', {}, { ...NO_FILTERS, contacts: ['c1'] }]
	])('leaves what a link brings alone (%s %o)', async (search, entry, remembered) => {
		rememberFilters({ ...NO_FILTERS, contacts: ['c1'] });
		state.url = new URL(`http://lekto/ui/documents${search}`);
		state.entry = entry;
		vi.stubGlobal(
			'fetch',
			fakeApi({ 'GET /api/v1/documents/stream': () => ({ lanes: [], truncated: false }) })
		);
		render(Page);
		await screen.findByRole('heading', { level: 1 });
		expect(vi.mocked(goto)).not.toHaveBeenCalled();
		expect(rememberedFilters()).toEqual(remembered);
	});

	it('remembers the filters as they change, and forgets them with a reset', async () => {
		state.url = new URL('http://lekto/ui/documents?contact=c1&tag=t1');
		vi.stubGlobal('fetch', fakeApi());
		const user = userEvent.setup();
		render(Page);
		await user.click(
			await screen.findByRole('button', { name: m.filter_tag_remove({ name: 't1' }) })
		);
		expect(rememberedFilters()).toEqual({ ...NO_FILTERS, contacts: ['c1'] });
		expect(vi.mocked(goto)).toHaveBeenLastCalledWith('?contact=c1', searching(''));
		await user.click(screen.getByRole('button', { name: m.filter_reset() }));
		expect(rememberedFilters()).toBeNull();
		expect(vi.mocked(goto)).toHaveBeenLastCalledWith('/ui/documents', searching(''));
	});

	it('does not remember the filters of a lens', async () => {
		state.url = new URL('http://lekto/ui/documents?lens=l1&tag=t1');
		vi.stubGlobal('fetch', fakeApi());
		const user = userEvent.setup();
		render(Page);
		await user.click(
			await screen.findByRole('button', { name: m.filter_tag_remove({ name: 't1' }) })
		);
		expect(vi.mocked(goto)).toHaveBeenLastCalledWith('?lens=l1', searching(''));
		expect(rememberedFilters()).toBeNull();
	});

	it('collapses the filters beside the list, counts the active ones, and remembers it', async () => {
		state.url = new URL('http://lekto/ui/documents?contact=c1&tag=t1');
		vi.stubGlobal('fetch', fakeApi());
		const user = userEvent.setup();
		render(Page);
		const aside = screen.getByRole('complementary', { name: m.filters_title() });
		const collapse = screen.getByRole('button', { name: m.filters_collapse() });
		expect(collapse.getAttribute('aria-expanded')).toBe('true');
		expect(collapse.getAttribute('aria-controls')).toBe(aside.id);
		await user.click(collapse);
		expect(screen.queryByRole('complementary', { name: m.filters_title() })).toBeNull();
		const expand = screen.getByRole('button', {
			name: m.filters_expand_active({ count: '2' })
		});
		expect(expand.getAttribute('aria-expanded')).toBe('false');
		expect(expand.hasAttribute('aria-controls')).toBe(false);
		expect(filtersCollapsed()).toBe(true);
		// The active filters stay as chips.
		expect(screen.getByRole('group', { name: m.filters_active() })).toBeTruthy();
		await user.click(expand);
		expect(screen.getByRole('complementary', { name: m.filters_title() })).toBeTruthy();
		expect(filtersCollapsed()).toBe(false);
	});

	it('opens with the filters collapsed as remembered', async () => {
		rememberFiltersCollapsed(true);
		vi.stubGlobal('fetch', fakeApi());
		render(Page);
		expect(screen.queryByRole('complementary', { name: m.filters_title() })).toBeNull();
		expect(screen.getByRole('button', { name: m.filters_expand() })).toBeTruthy();
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
