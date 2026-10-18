import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { goto } from '$app/navigation';
import type { components } from '#lib/api/schema.ts';
import { events } from '#lib/events.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
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
	events.stop();
	session.clear();
	vi.unstubAllGlobals();
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
