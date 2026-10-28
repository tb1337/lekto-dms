import { fireEvent, render, screen, within } from '@testing-library/svelte';
import { userEvent } from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatNumber } from '#lib/i18n.ts';
import { usageLabel } from '#lib/components/UsageCount.svelte';
import { NODE_LABELS } from '#lib/node-labels.ts';
import { m } from '#lib/paraglide/messages.js';
import { forgetPipeline } from '#lib/pipeline.ts';
import { choose } from '#lib/testing/select.ts';
import { fakeApi } from '#lib/testing/documents.ts';
import { BulkRun } from '#lib/bulk.svelte.ts';
import DocumentsBulkBar from './DocumentsBulkBar.svelte';

const node = (name: string, requires: string[] = []) => ({ node: name, requires, waits_for: [] });
const GRAPH = [
	node('receive'),
	node('ocr', ['receive']),
	node('parse', ['ocr']),
	node('signal_llm', ['parse']),
	node('judge', ['signal_llm']),
	node('file', ['judge'])
];

afterEach(() => {
	forgetPipeline();
	vi.unstubAllGlobals();
});

function renderBar(count: number) {
	const run = new BulkRun(vi.fn());
	const rendered = render(DocumentsBulkBar, {
		count,
		all: false,
		offerAll: null,
		limit: null,
		capped: null,
		selection: () => ({ ids: ['d1'], query: {} }),
		run,
		lookup: { contacts: [], documentTypes: [], tags: [], fields: [], spaces: [], users: [] },
		onpage: vi.fn(),
		onall: vi.fn(),
		onclear: vi.fn(),
		onend: vi.fn()
	});
	return { ...rendered, run };
}

describe('the selection bar of the documents', () => {
	it('reprocesses from a chosen step, and says what the model costs for many', async () => {
		const sent: unknown[] = [];
		vi.stubGlobal(
			'fetch',
			fakeApi({
				'GET /api/v1/pipeline': () => ({ nodes: GRAPH, vision: null }),
				'POST /api/v1/documents/bulk': async (request) => {
					sent.push(await request.json());
					return { id: 'op', status: 'queued', total: 40, done: 0, skipped: [] };
				}
			})
		);
		renderBar(40);
		const more = screen.getByRole('button', { name: m.bulk_more() });
		await fireEvent.pointerDown(more, { button: 0, pointerType: 'mouse' });
		await userEvent.click(await screen.findByRole('menuitem', { name: m.bulk_reprocess() }));
		const dialog = await screen.findByRole('dialog', {
			name: m.bulk_reprocess_title({ documents: usageLabel(40) })
		});
		const warning = m.bulk_reprocess_model({ calls: formatNumber(80) });
		// From the text recognition on, the model is asked too.
		await vi.waitFor(() => expect(dialog.textContent).toContain(warning));
		const step = within(dialog).getByRole('combobox', { name: m.reprocess_from() });
		await vi.waitFor(() => expect(step.textContent).toContain(NODE_LABELS.ocr()));
		await choose(userEvent.setup(), step, 'judge');
		expect(dialog.textContent).not.toContain(warning);
		await userEvent.click(within(dialog).getByRole('button', { name: m.reprocess_title() }));
		await vi.waitFor(() =>
			expect(sent).toEqual([
				{ document_ids: ['d1'], action: { kind: 'reprocess', from_node: 'judge' } }
			])
		);
	});

	it('says nothing of the model for a few documents', async () => {
		vi.stubGlobal(
			'fetch',
			fakeApi({ 'GET /api/v1/pipeline': () => ({ nodes: GRAPH, vision: null }) })
		);
		renderBar(3);
		await fireEvent.pointerDown(screen.getByRole('button', { name: m.bulk_more() }), {
			button: 0,
			pointerType: 'mouse'
		});
		await userEvent.click(await screen.findByRole('menuitem', { name: m.bulk_reprocess() }));
		const dialog = await screen.findByRole('dialog');
		const step = within(dialog).getByRole('combobox', { name: m.reprocess_from() });
		await vi.waitFor(() => expect(step.textContent).toContain(NODE_LABELS.ocr()));
		expect(dialog.textContent).not.toContain(m.bulk_reprocess_model({ calls: '6' }));
	});
});
