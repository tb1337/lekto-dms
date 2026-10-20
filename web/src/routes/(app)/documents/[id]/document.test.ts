import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { goto } from '$app/navigation';
import type { components } from '#lib/api/schema.ts';
import type { Facts } from '#lib/facts.ts';
import { events } from '#lib/events.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { phone } from '#lib/phone.svelte.ts';
import { session } from '#lib/session.svelte.ts';
import {
	calls,
	documentOf,
	fakeApi,
	inboxItem,
	json,
	OWNER,
	summaryOf
} from '#lib/testing/documents.ts';
import { goTo } from '#lib/testing/page-state.svelte.ts';
import Page from './+page.svelte';

type Document = components['schemas']['DocumentDetails'];

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

let emit: ((type: string, data: object) => void) | null = null;

function streamEvents() {
	const listeners = new Map<string, (message: { data: string }) => void>();
	events.useFactory(
		() =>
			({
				addEventListener(type: string, handler: (message: { data: string }) => void) {
					listeners.set(type, handler);
				},
				close() {}
			}) as unknown as EventSource
	);
	events.start(() => {});
	emit = (type, data) =>
		listeners.get(type)?.({
			data: JSON.stringify({ type, id: crypto.randomUUID(), occurred_at: '', ...data })
		});
}

/** The routes of one document's view. */
function documentRoutes(id: string, current: () => Document): Parameters<typeof fakeApi>[0] {
	return {
		[`GET /api/v1/documents/${id}`]: () => current(),
		[`GET /api/v1/documents/${id}/review`]: () => ({ document: current(), open: [], nodes: [] }),
		[`GET /api/v1/documents/${id}/reading`]: () => ({ vision: false, pages: [], advice: null }),
		// The metadata tab says so; the test looks at seen.
		[`GET /api/v1/documents/${id}/files`]: () =>
			json({ type: 'about:blank', title: 'Not Found', status: 404 }, 404)
	};
}

function serve(current: () => Document, routes: Parameters<typeof fakeApi>[0] = {}) {
	const api = fakeApi({
		...documentRoutes('doc-1', current),
		'GET /api/v1/pipeline': () => ({ nodes: [], vision: null }),
		'GET /api/v1/inbox/summary': () => summaryOf(),
		...routes
	});
	vi.stubGlobal('fetch', api);
	return api;
}

const seen = (api: ReturnType<typeof fakeApi>) =>
	calls(api).filter((call) => call === 'PUT /api/v1/documents/doc-1/seen');

beforeEach(() => {
	goTo('/ui/documents/doc-1?tab=metadata', { id: 'doc-1' });
	vi.mocked(goto).mockClear();
	session.start({
		user: { id: OWNER, username: 'tobi', role: 'user' },
		method: 'password',
		expires_at: '2026-10-18T12:00:00Z',
		csrf_token: 'token'
	});
	streamEvents();
});

afterEach(() => {
	phone.override(null);
	events.stop();
	session.clear();
	vi.unstubAllGlobals();
	localStorage.clear();
});

describe('the document view and seen', () => {
	it('reports seen when it opens, and refreshes the counter', async () => {
		const api = serve(() => documentOf({ lane: 'green' }));
		render(Page);
		await waitFor(() => expect(seen(api)).toHaveLength(1));
		await waitFor(() => expect(calls(api)).toContain('GET /api/v1/inbox/summary'));
		// Further loads of the same document report nothing new.
		emit?.('document.updated', { document_id: 'doc-1', fields: ['title'] });
		await waitFor(() =>
			expect(calls(api).filter((call) => call === 'GET /api/v1/documents/doc-1')).toHaveLength(2)
		);
		expect(seen(api)).toHaveLength(1);
	});

	it('asks for no facts before the document has its text', async () => {
		const api = serve(() => documentOf({ lane: null }));
		render(Page);
		await waitFor(() => expect(seen(api)).toHaveLength(1));
		expect(calls(api)).not.toContain('GET /api/v1/documents/doc-1/facts');
	});

	it('reports seen again when the open document turns green', async () => {
		let current = documentOf({ lane: null });
		const api = serve(() => current);
		render(Page);
		await waitFor(() => expect(seen(api)).toHaveLength(1));
		emit?.('document.node_completed', { document_id: 'doc-1', node: 'ocr', run: 1, outcome: 'ok' });
		await waitFor(() =>
			expect(calls(api).filter((call) => call === 'GET /api/v1/documents/doc-1')).toHaveLength(2)
		);
		expect(seen(api)).toHaveLength(1);
		current = documentOf({ lane: 'green' });
		emit?.('document.lane_changed', { document_id: 'doc-1', old: null, new: 'green' });
		await waitFor(() => expect(seen(api)).toHaveLength(2));
	});

	it('reports seen of a document opened from the inbox once the inbox is known', async () => {
		goTo('/ui/documents/doc-1?from=inbox&tab=metadata', { id: 'doc-1' });
		const api = serve(() => documentOf({ lane: 'green' }), {
			'GET /api/v1/inbox': () => ({
				items: [inboxItem('new', { id: 'doc-0' }), inboxItem('new', { id: 'doc-1' })],
				next_cursor: null
			})
		});
		render(Page);
		await waitFor(() => expect(seen(api)).toHaveLength(1));
		const order = calls(api);
		expect(order.indexOf('GET /api/v1/inbox?limit=100')).toBeLessThan(
			order.indexOf('PUT /api/v1/documents/doc-1/seen')
		);
		expect(await screen.findByText(m.doc_inbox_position({ position: 2, total: 2 }))).toBeTruthy();
	});
});

describe('confirming from the inbox', () => {
	it('opens next the document that waits for a decision', async () => {
		goTo('/ui/documents/doc-1?from=inbox', { id: 'doc-1' });
		const yellow = documentOf({
			lane: 'yellow',
			processing: { ...documentOf().processing, status: 'review' }
		});
		const api = serve(() => yellow, {
			'GET /api/v1/documents/doc-1/review': () => ({
				document: yellow,
				open: [{ node: 'judge', outcome: 'uncertain', reason: 'Widerspruch', fields: [] }],
				nodes: []
			}),
			'GET /api/v1/documents/doc-1/original': () => new Response('', { status: 404 }),
			'GET /api/v1/inbox': () => ({
				items: [
					inboxItem('review', { id: 'doc-1' }),
					inboxItem('new', { id: 'doc-new' }),
					inboxItem('processing', { id: 'doc-running' }),
					inboxItem('intervene', { id: 'doc-red' })
				],
				next_cursor: null
			})
		});
		render(Page);
		const next = await screen.findByRole('checkbox', { name: m.review_next_document() });
		expect((next as HTMLInputElement).checked).toBe(true);
		await userEvent.click(screen.getByRole('button', { name: m.review_confirm() }));
		await waitFor(() => expect(calls(api)).toContain('POST /api/v1/documents/doc-1/confirm'));
		await waitFor(() => expect(goto).toHaveBeenCalledWith('/ui/documents/doc-red?from=inbox'));
	});

	it('goes back to the inbox when nothing else waits for a decision', async () => {
		goTo('/ui/documents/doc-1?from=inbox', { id: 'doc-1' });
		const yellow = documentOf({
			lane: 'yellow',
			processing: { ...documentOf().processing, status: 'review' }
		});
		serve(() => yellow, {
			'GET /api/v1/documents/doc-1/review': () => ({
				document: yellow,
				open: [{ node: 'judge', outcome: 'uncertain', reason: 'Widerspruch', fields: [] }],
				nodes: []
			}),
			'GET /api/v1/documents/doc-1/original': () => new Response('', { status: 404 }),
			'GET /api/v1/inbox': () => ({
				items: [inboxItem('review', { id: 'doc-1' }), inboxItem('new', { id: 'doc-new' })],
				next_cursor: null
			})
		});
		render(Page);
		const confirm = await screen.findByRole('button', { name: m.review_confirm() });
		expect(screen.queryByRole('checkbox', { name: m.review_next_document() })).toBeNull();
		await userEvent.click(confirm);
		await waitFor(() => expect(goto).toHaveBeenCalledWith('/ui/inbox'));
	});

	it('offers next no document confirmed before', async () => {
		goTo('/ui/documents/doc-1?from=inbox', { id: 'doc-1' });
		const yellow = (id: string) =>
			documentOf({
				id,
				lane: 'yellow',
				processing: { ...documentOf().processing, status: 'review' }
			});
		const open = (id: string) => () => ({
			document: yellow(id),
			open: [{ node: 'judge', outcome: 'uncertain', reason: 'Widerspruch', fields: [] }],
			nodes: []
		});
		let confirmedOne = false;
		const api = serve(() => yellow('doc-1'), {
			'GET /api/v1/documents/doc-1/review': open('doc-1'),
			...documentRoutes('doc-2', () => yellow('doc-2')),
			'GET /api/v1/documents/doc-2/review': open('doc-2'),
			'POST /api/v1/documents/doc-1/confirm': () => {
				confirmedOne = true;
				return yellow('doc-1');
			},
			// Once confirmed, doc-1 is processed on: it waits for no decision any more.
			'GET /api/v1/inbox': () => ({
				items: confirmedOne
					? [inboxItem('review', { id: 'doc-2' }), inboxItem('processing', { id: 'doc-1' })]
					: [inboxItem('review', { id: 'doc-1' }), inboxItem('review', { id: 'doc-2' })],
				next_cursor: null
			})
		});
		render(Page);
		await userEvent.click(await screen.findByRole('button', { name: m.review_confirm() }));
		await waitFor(() => expect(goto).toHaveBeenCalledWith('/ui/documents/doc-2?from=inbox'));
		goTo('/ui/documents/doc-2?from=inbox', { id: 'doc-2' });
		await waitFor(() => expect(calls(api)).toContain('GET /api/v1/documents/doc-2/review'));
		await waitFor(() =>
			expect(screen.queryByRole('checkbox', { name: m.review_next_document() })).toBeNull()
		);
		await userEvent.click(await screen.findByRole('button', { name: m.review_confirm() }));
		await waitFor(() => expect(calls(api)).toContain('POST /api/v1/documents/doc-2/confirm'));
		await waitFor(() => expect(goto).toHaveBeenLastCalledWith('/ui/inbox'));
	});
});

describe('the document tab', () => {
	const TEXT = 'Kundennummer EBeschV 4711\n\f\nSeite zwei';
	const FACTS: Facts = {
		contact_id: null,
		named: [],
		identifiers: [
			{
				kind: 'customer_number',
				value: 'EBeschV',
				contact_id: null,
				in_text: true,
				in_code: false,
				spans: [{ start: 13, end: 20, locations: [] }],
				other_contacts: null
			}
		],
		codes: []
	};
	const readable = {
		'GET /api/v1/documents/doc-1/text': () => ({
			text: TEXT,
			offset: 0,
			total_length: TEXT.length,
			next_offset: null
		}),
		'GET /api/v1/documents/doc-1/facts': () => FACTS
	};
	// Read again: it has its text.
	const parsed = () =>
		documentOf({ lane: 'green', processing: { ...documentOf().processing, run: 2 } });
	const titleField = () =>
		globalThis.document.getElementById('doc-title') as HTMLInputElement | null;

	it('opens a link of before on the text and the facts, and marks a fact in the text', async () => {
		Element.prototype.scrollIntoView = vi.fn();
		goTo('/ui/documents/doc-1?tab=content', { id: 'doc-1' });
		serve(parsed, readable);
		render(Page);
		const facts = await screen.findByRole('complementary', { name: m.facts_title() });
		await screen.findByRole('region', { name: m.content_page({ page: 1 }) });
		await userEvent.click(await within(facts).findByRole('button', { name: /EBeschV/ }));
		expect(globalThis.document.querySelector('mark[data-mark]')?.textContent).toBe('EBeschV');
		// The browser remembers the view; a switch puts it in the link.
		expect(JSON.parse(localStorage.getItem('lekto.document.view') ?? '')).toEqual({
			left: 'text',
			right: 'facts'
		});
		const left = screen.getByRole('group', { name: m.view_left() });
		await userEvent.click(within(left).getByRole('button', { name: m.view_pages() }));
		expect(goto).toHaveBeenCalledWith('/ui/documents/doc-1?left=pages&right=facts', {
			replace: true,
			reset: false
		});
	});

	it('marks the quote of a field in the text while the field is hovered', async () => {
		goTo('/ui/documents/doc-1?left=text&right=form', { id: 'doc-1' });
		const dated = () => ({ ...parsed(), document_date: '2026-03-12' });
		const date = {
			field: 'document_date',
			outcome: 'ok',
			confidence: 1,
			reason: null,
			proposed: null,
			evidence: 'EBeschV 4711',
			value: '2026-03-12',
			suggestion: null,
			new_name: null,
			quote_shows_value: true,
			locations: [{ page: 1, boxes: [{ x: 0.1, y: 0.2, width: 0.3, height: 0.02 }] }],
			candidates: []
		};
		serve(dated, {
			...readable,
			'GET /api/v1/documents/doc-1/review': () => ({
				document: dated(),
				open: [],
				nodes: [{ node: 'fields', run: 2, outcome: 'ok', reason: null, fields: [date] }]
			})
		});
		render(Page);
		await screen.findByRole('region', { name: m.content_page({ page: 1 }) });
		await fireEvent.mouseEnter(await screen.findByRole('group', { name: m.field_date() }));
		await waitFor(() =>
			expect(globalThis.document.querySelector('mark[data-mark]')?.textContent).toBe('EBeschV 4711')
		);
		// Gone once the pointer leaves the field.
		await fireEvent.mouseLeave(screen.getByRole('group', { name: m.field_date() }));
		await waitFor(() => expect(globalThis.document.querySelector('mark[data-mark]')).toBeNull());
	});

	it('keeps what was typed in the form while the facts are shown', async () => {
		localStorage.setItem('lekto.document.view', JSON.stringify({ left: 'text', right: 'form' }));
		goTo('/ui/documents/doc-1', { id: 'doc-1' });
		serve(parsed, readable);
		render(Page);
		await waitFor(() => expect(titleField()).not.toBeNull());
		await userEvent.clear(titleField()!);
		await userEvent.type(titleField()!, 'Neu');
		goTo('/ui/documents/doc-1?left=text&right=facts', { id: 'doc-1' });
		await screen.findByRole('complementary', { name: m.facts_title() });
		// Hidden, not gone.
		expect(screen.queryByRole('form', { name: m.edit_title() })).toBeNull();
		expect(titleField()?.value).toBe('Neu');
		goTo('/ui/documents/doc-1?left=text&right=form', { id: 'doc-1' });
		await waitFor(() => expect(screen.getByRole('form', { name: m.edit_title() })).toBeTruthy());
		expect(titleField()?.value).toBe('Neu');
	});

	it('shows a pane chosen deep down the one before from its start, on a phone', async () => {
		phone.override(true);
		const scrolled = vi.fn();
		Element.prototype.scrollIntoView = scrolled;
		goTo('/ui/documents/doc-1?left=text&right=facts', { id: 'doc-1' });
		serve(parsed, readable);
		render(Page);
		const bar = await screen.findByRole('group', { name: m.view_pane() });
		// Far down the text: the panes start above the window.
		vi.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue({
			top: -2000,
			bottom: 400,
			left: 0,
			right: 390
		} as DOMRect);
		await userEvent.click(within(bar).getByRole('button', { name: m.view_facts() }));
		await waitFor(() => expect(scrolled).toHaveBeenCalledWith({ block: 'start' }));
		vi.restoreAllMocks();
	});

	it('shows one pane at a time on a phone, and a tapped fact where it stands', async () => {
		phone.override(true);
		Element.prototype.scrollIntoView = vi.fn();
		goTo('/ui/documents/doc-1?left=text&right=facts', { id: 'doc-1' });
		serve(parsed, readable);
		render(Page);
		const bar = await screen.findByRole('group', { name: m.view_pane() });
		const text = () => screen.queryByRole('region', { name: m.content_page({ page: 1 }) });
		await waitFor(() => expect(text()).not.toBeNull());
		// The bar of four instead of the panes' switches; the right pane hidden.
		expect(screen.queryByRole('group', { name: m.view_left() })).toBeNull();
		expect(screen.queryByRole('complementary', { name: m.facts_title() })).toBeNull();
		await userEvent.click(within(bar).getByRole('button', { name: m.view_facts() }));
		const facts = await screen.findByRole('complementary', { name: m.facts_title() });
		expect(text()).toBeNull();
		// A tap on a fact shows the text again, the fact marked in it.
		await userEvent.click(await within(facts).findByRole('button', { name: /EBeschV/ }));
		await waitFor(() => expect(text()).not.toBeNull());
		expect(globalThis.document.querySelector('mark[data-mark]')?.textContent).toBe('EBeschV');
		const shown = within(bar).getByRole('button', { name: m.view_text() });
		expect(shown.getAttribute('aria-pressed')).toBe('true');
		// The pages: the left pane shows them, the link says so.
		await userEvent.click(within(bar).getByRole('button', { name: m.view_pages() }));
		expect(goto).toHaveBeenCalledWith('/ui/documents/doc-1?left=pages&right=facts', {
			replace: true,
			reset: false
		});
	});
});
