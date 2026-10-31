import { render, screen, within } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import { reasonText, type Reason } from '#lib/reasons.ts';
import { documentOf, fakeApi } from '#lib/testing/documents.ts';
import BulkSkipped from './BulkSkipped.svelte';

afterEach(() => vi.unstubAllGlobals());

const reason = (code: Reason['code'], params: Reason['params'] = {}): Reason => ({ code, params });

describe('the skipped documents of an action on many', () => {
	it('names each by title with why, and one no longer readable by its reason alone', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/documents/d1': () => documentOf({ id: 'd1', title: 'Strom 2026' }),
				'GET /api/v1/documents/d2': () => new Response(null, { status: 404 })
			})
		);
		const busy = reason('being_processed', { id: 'd1' });
		const gone = reason('skip_not_available');
		render(BulkSkipped, {
			operation: {
				id: 'op',
				kind: 'change_tags',
				status: 'done',
				total: 3,
				done: 3,
				changed: 1,
				unchanged: 0,
				skipped: [
					{ document_id: 'd1', reason: 'busy', reasons: [busy] },
					{ document_id: 'd2', reason: 'gone', reasons: [gone] }
				],
				error: null,
				created_at: '2026-10-29T12:00:00Z',
				finished_at: '2026-10-29T12:00:05Z'
			},
			onclose: vi.fn()
		});
		const dialog = await screen.findByRole('dialog', { name: m.bulk_details_title() });
		await within(dialog).findByRole('button', { name: m.beam_open_named({ title: 'Strom 2026' }) });
		expect(dialog.textContent).toContain(reasonText(busy));
		await vi.waitFor(() => expect(dialog.textContent).toContain(m.bulk_unknown_document()));
		expect(dialog.textContent).toContain(reasonText(gone));
	});

	it('asks for each document once, however the answers come in', async () => {
		const ids = ['d1', 'd2', 'd3', 'd4'];
		const api = fakeApi(
			Object.fromEntries(
				ids.map((id) => [
					`GET /api/v1/documents/${id}`,
					() => documentOf({ id, title: `Dokument ${id}` })
				])
			)
		);
		vi.stubGlobal('fetch', api);
		render(BulkSkipped, {
			operation: {
				id: 'op',
				kind: 'delete',
				status: 'done',
				total: 4,
				done: 4,
				changed: 0,
				unchanged: 0,
				skipped: ids.map((id) => ({ document_id: id, reason: 'busy', reasons: [] })),
				error: null,
				created_at: '2026-10-28T12:00:00Z',
				finished_at: '2026-10-28T12:00:05Z'
			},
			onclose: vi.fn()
		});
		const dialog = await screen.findByRole('dialog', { name: m.bulk_details_title() });
		for (const id of ids)
			await within(dialog).findByRole('button', {
				name: m.beam_open_named({ title: `Dokument ${id}` })
			});
		const asked = api.mock.calls.map(([request]) => new URL(request.url).pathname).sort();
		expect(asked).toEqual(ids.map((id) => `/api/v1/documents/${id}`));
	});
});
