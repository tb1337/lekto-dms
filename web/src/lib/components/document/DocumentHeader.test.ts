import { fireEvent, render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import type { GraphNode } from '#lib/pipeline.ts';
import { session } from '#lib/session.svelte.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { choose, optionsOf } from '#lib/testing/select.ts';
import type { Reading } from '#lib/vision.ts';
import { goto } from '$app/navigation';
import DocumentHeader from './DocumentHeader.svelte';

vi.mock('$app/navigation', () => ({ goto: vi.fn() }));

type Document = components['schemas']['DocumentDetails'];

const OWNER = 'user-1';
const VISION = { model: 'claude-sonnet', endpoint: 'chat.example' };
const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

const graph: GraphNode[] = [
	{ node: 'receive', requires: [], waits_for: [] },
	{ node: 'ocr', requires: ['receive'], waits_for: [] },
	{ node: 'pages', requires: ['receive'], waits_for: [] },
	{ node: 'parse', requires: ['ocr'], waits_for: [] },
	{ node: 'file', requires: ['parse', 'pages'], waits_for: [] }
];

function document(outcome: 'ok' | 'failed' = 'ok'): Document {
	return {
		id: 'doc-1',
		title: 'Scan',
		original_filename: 'scan.pdf',
		uploaded_by: OWNER,
		space_id: 'space-1',
		access: 'edit',
		lane: outcome === 'failed' ? 'red' : 'yellow',
		page_count: 1,
		created_at: '2026-10-15T08:00:00Z',
		processing: {
			status: outcome === 'failed' ? 'failed' : 'review',
			run: 1,
			vision: false,
			nodes: graph.map(({ node }) => ({
				node,
				status: node === 'file' ? 'waiting' : 'done',
				outcome: node === 'file' ? null : node === 'parse' ? outcome : 'ok',
				started_at: null,
				finished_at: null
			}))
		}
	} as unknown as Document;
}

const NO_TEXT: Reading = {
	vision: false,
	pages: [{ page: 1, words: 0, unsure: 0, content: 0, content_unsure: 0, poor: false }],
	advice: 'no_text'
};

function props(overrides: Record<string, unknown> = {}) {
	return {
		document: document('failed'),
		lookup: null,
		graph,
		archive: true,
		inbox: null,
		vision: VISION,
		reading: NO_TEXT,
		onchanged: vi.fn(),
		...overrides
	};
}

beforeEach(() => {
	session.start({
		user: { id: OWNER, username: 'tobi', role: 'user' },
		method: 'password',
		expires_at: '2026-10-15T12:00:00Z',
		csrf_token: 'token'
	});
	fetchMock.mockReset();
	fetchMock.mockImplementation(async () => new Response('{}', { status: 202 }));
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
	session.clear();
	vi.unstubAllGlobals();
});

/** The menu of further actions; bits-ui opens it on a pointer press. */
async function openMenu() {
	await fireEvent.pointerDown(screen.getByRole('button', { name: m.doc_more() }), {
		button: 0,
		pointerType: 'mouse'
	});
	return userEvent.setup();
}

describe('DocumentHeader', () => {
	it('offers reading with the model, marked when advised', async () => {
		render(DocumentHeader, props());
		await openMenu();
		const item = await screen.findByRole('menuitem', { name: new RegExp(m.vision_read()) });
		expect(within(item).getByText(m.vision_recommended())).toBeTruthy();
	});

	it('asks before the pages go out, naming where, and then sends the request', async () => {
		const onchanged = vi.fn();
		render(DocumentHeader, props({ onchanged }));
		const user = await openMenu();
		await user.click(await screen.findByRole('menuitem', { name: new RegExp(m.vision_read()) }));
		const dialog = await screen.findByRole('alertdialog');
		expect(dialog.textContent).toContain(m.vision_advice_no_text());
		expect(dialog.textContent).toContain(
			m.vision_hint({ endpoint: 'chat.example', model: 'claude-sonnet' })
		);
		expect(fetchMock).not.toHaveBeenCalled();
		await user.click(within(dialog).getByRole('button', { name: m.vision_read() }));
		await waitFor(() => expect(onchanged).toHaveBeenCalled());
		const [request] = fetchMock.mock.calls[0];
		expect(request.method).toBe('POST');
		expect(new URL(request.url).pathname).toBe('/api/v1/documents/doc-1/vision');
	});

	it('runs the failed step again from the menu', async () => {
		const onchanged = vi.fn();
		render(DocumentHeader, props({ onchanged }));
		const user = await openMenu();
		await user.click(await screen.findByRole('menuitem', { name: m.retry_node() }));
		await waitFor(() => expect(onchanged).toHaveBeenCalled());
		const [request] = fetchMock.mock.calls[0];
		expect(request.method).toBe('POST');
		expect(new URL(request.url).pathname).toBe('/api/v1/documents/doc-1/retry');
	});

	it('offers nothing without a model', async () => {
		render(DocumentHeader, props({ vision: null }));
		await openMenu();
		await screen.findByRole('menuitem', { name: m.delete_title() });
		expect(screen.queryByRole('menuitem', { name: new RegExp(m.vision_read()) })).toBeNull();
	});

	it('is not marked without advice', async () => {
		render(DocumentHeader, props({ document: document(), reading: { ...NO_TEXT, advice: null } }));
		await openMenu();
		const item = await screen.findByRole('menuitem', { name: m.vision_read() });
		expect(within(item).queryByText(m.vision_recommended())).toBeNull();
	});

	describe('reprocessing from OCR a document the model read', () => {
		const read = { ...NO_TEXT, vision: true, advice: null };

		async function openReprocess(overrides: Record<string, unknown> = {}) {
			render(DocumentHeader, props({ document: document(), reading: read, ...overrides }));
			const user = await openMenu();
			await user.click(await screen.findByRole('menuitem', { name: m.reprocess_title() }));
			return { user, dialog: await screen.findByRole('dialog') };
		}

		it('reads with the model again when the person keeps that, naming where', async () => {
			const { user, dialog } = await openReprocess();
			const again = within(dialog).getByRole('checkbox', { name: m.reprocess_vision_again() });
			expect(again.getAttribute('aria-checked')).toBe('true');
			expect(dialog.textContent).toContain(
				m.vision_hint({ endpoint: 'chat.example', model: 'claude-sonnet' })
			);
			await user.click(within(dialog).getByRole('button', { name: m.reprocess_with_vision() }));
			await waitFor(() => expect(fetchMock).toHaveBeenCalled());
			const [request] = fetchMock.mock.calls[0];
			expect(new URL(request.url).pathname).toBe('/api/v1/documents/doc-1/vision');
		});

		it('reads with Tesseract when the person says no, and warns', async () => {
			const { user, dialog } = await openReprocess();
			await user.click(within(dialog).getByRole('checkbox', { name: m.reprocess_vision_again() }));
			expect(within(dialog).getByText(m.reprocess_vision_lost())).toBeTruthy();
			await user.click(within(dialog).getByRole('button', { name: m.reprocess_title() }));
			await waitFor(() => expect(fetchMock).toHaveBeenCalled());
			const [request] = fetchMock.mock.calls[0];
			expect(new URL(request.url).pathname).toBe('/api/v1/documents/doc-1/reprocess');
			expect(await request.json()).toEqual({ from_node: 'ocr' });
		});

		it('only warns without a model', async () => {
			const { dialog } = await openReprocess({ vision: null });
			expect(within(dialog).queryByRole('checkbox')).toBeNull();
			expect(within(dialog).getByText(m.reprocess_vision_lost())).toBeTruthy();
		});
	});

	describe('space', () => {
		const lookup = {
			users: [
				{ id: OWNER, username: 'tobi', role: 'user', personal_space_id: 'space-2' },
				{ id: 'user-2', username: 'anna', role: 'user', personal_space_id: 'space-3' }
			],
			spaces: [
				{
					id: 'space-1',
					name: 'Haushalt',
					personal_of: null,
					role: 'edit',
					members: [
						{ user_id: OWNER, role: 'edit', username: 'tobi', active: true },
						{ user_id: 'user-2', role: 'read', username: 'anna', active: true }
					]
				},
				{
					id: 'space-2',
					name: 'Personal',
					personal_of: OWNER,
					role: 'edit',
					members: [{ user_id: OWNER, role: 'edit', username: 'tobi', active: true }]
				},
				{
					id: 'space-3',
					name: 'Personal',
					personal_of: 'user-2',
					role: 'read',
					members: [
						{ user_id: 'user-2', role: 'edit', username: 'anna', active: true },
						{ user_id: OWNER, role: 'read', username: 'tobi', active: true }
					]
				}
			]
		} as unknown as Lookup;

		it('names the space and who else sees the document: readers once it is green', () => {
			const green = { ...document(), lane: 'green' } as Document;
			const { unmount } = render(DocumentHeader, props({ lookup, document: green }));
			expect(screen.getByText(new RegExp(m.visible_to({ names: 'anna' })))).toBeTruthy();
			unmount();
			render(DocumentHeader, props({ lookup }));
			expect(screen.getByText(new RegExp(m.visible_to_you()))).toBeTruthy();
			expect(
				screen.getByText(new RegExp(m.visible_to_readers_later({ names: 'anna' })))
			).toBeTruthy();
		});

		it('moves into an edited space or hands over into another personal one', async () => {
			const onchanged = vi.fn();
			render(DocumentHeader, props({ lookup, onchanged }));
			// A dialog of an earlier test may still leave the body without pointer events.
			const user = userEvent.setup({ pointerEventsCheck: 0 });
			await user.click(screen.getByRole('button', { name: m.move_title() }));
			const dialog = await screen.findByRole('dialog');
			const field = within(dialog).getByLabelText(m.field_space());
			expect(await optionsOf(field)).toEqual([
				{ value: 'space-2', label: m.space_personal() },
				{ value: 'space-3', label: m.move_hand_over({ name: 'anna' }) }
			]);
			await user.click(within(dialog).getByRole('button', { name: m.move_title() }));
			await waitFor(() => expect(onchanged).toHaveBeenCalled());
			const [request] = fetchMock.mock.calls[0];
			expect(new URL(request.url).pathname).toBe('/api/v1/documents/doc-1/move');
			expect(await request.json()).toEqual({ space_id: 'space-2' });
		});

		it('goes back to the documents after handing the document over', async () => {
			const onchanged = vi.fn();
			render(DocumentHeader, props({ lookup, onchanged }));
			const user = userEvent.setup({ pointerEventsCheck: 0 });
			await user.click(screen.getByRole('button', { name: m.move_title() }));
			const dialog = await screen.findByRole('dialog');
			await choose(user, within(dialog).getByLabelText(m.field_space()), 'space-3');
			await user.click(within(dialog).getByRole('button', { name: m.move_title() }));
			await waitFor(() => expect(goto).toHaveBeenCalledWith('/ui/documents'));
			expect(await fetchMock.mock.calls[0][0].json()).toEqual({ space_id: 'space-3' });
			expect(onchanged).not.toHaveBeenCalled();
		});

		it('hands over to a user whose personal space the caller is no member of', async () => {
			const strangers = {
				...lookup,
				spaces: lookup.spaces.filter((space) => space.id !== 'space-3')
			} as Lookup;
			const onchanged = vi.fn();
			render(DocumentHeader, props({ lookup: strangers, onchanged }));
			const user = userEvent.setup({ pointerEventsCheck: 0 });
			await user.click(screen.getByRole('button', { name: m.move_title() }));
			const dialog = await screen.findByRole('dialog');
			await choose(user, within(dialog).getByLabelText(m.field_space()), 'space-3');
			await user.click(within(dialog).getByRole('button', { name: m.move_title() }));
			await waitFor(() => expect(goto).toHaveBeenCalledWith('/ui/documents'));
			expect(await fetchMock.mock.calls[0][0].json()).toEqual({ space_id: 'space-3' });
			expect(onchanged).not.toHaveBeenCalled();
		});

		it('offers a reader no move', () => {
			render(
				DocumentHeader,
				props({ lookup, document: { ...document(), access: 'read' } as Document })
			);
			expect(screen.queryByRole('button', { name: m.move_title() })).toBeNull();
			expect(screen.queryByRole('button', { name: m.doc_more() })).toBeNull();
		});
	});
});
