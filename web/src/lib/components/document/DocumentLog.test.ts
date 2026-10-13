import { fireEvent, render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';
import type { GraphNode } from '#lib/pipeline.ts';
import DocumentLog from './DocumentLog.svelte';

type Document = components['schemas']['DocumentDetails'];

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

function json(body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'content-type': 'application/json' }
	});
}

const graph: GraphNode[] = [
	{ node: 'receive', requires: [] },
	{ node: 'ocr', requires: ['receive'] },
	{ node: 'pages', requires: ['receive'] },
	{ node: 'signal_llm', requires: ['ocr'] },
	{ node: 'judge', requires: ['signal_llm'] }
];

function state(node: string, outcome: string | null, status = 'done') {
	return {
		node,
		status,
		outcome,
		started_at: '2026-10-13T09:14:22Z',
		finished_at: status === 'done' ? '2026-10-13T09:14:28Z' : null
	};
}

const document = {
	id: 'doc-1',
	processing: {
		status: 'review',
		run: 1,
		nodes: [
			state('receive', 'ok'),
			state('ocr', 'ok'),
			state('pages', 'ok'),
			state('signal_llm', 'ok'),
			state('judge', 'uncertain')
		]
	}
} as unknown as Document;

const proposed = {
	node: 'signal_llm',
	run: 1,
	outcome: 'ok',
	reason: null,
	confidence: null,
	model_version: 'qwen3:8b',
	input: {},
	output: {
		tokens: [
			{ prompt: 2318, completion: 184, usage: { prompt_tokens: 2318, completion_tokens: 184 } }
		]
	},
	pipeline_version: 'test',
	started_at: '2026-10-13T09:14:22Z',
	duration_ms: 6300
};

const judged = {
	...proposed,
	node: 'judge',
	outcome: 'uncertain',
	reason: 'contact: the name is only similar',
	confidence: 0.62,
	output: {},
	duration_ms: 12
};

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (request) => {
		const path = new URL(request.url).pathname;
		if (path.endsWith('/log')) return json([proposed, judged]);
		if (path.endsWith('/exchanges/signal_llm')) {
			return json([
				{
					run: 1,
					calls: [
						{
							system: 'You read one document.',
							user: 'Contacts: …',
							answer: '{"contact": null}',
							model: 'qwen3:8b',
							usage: { prompt_tokens: 2318, completion_tokens: 184 }
						}
					]
				}
			]);
		}
		return json([]);
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe('DocumentLog', () => {
	it('shows the nodes in rows by level, side by side where they run so', async () => {
		const { container } = render(DocumentLog, {
			document,
			graph,
			manageable: true,
			onreprocess: vi.fn()
		});
		const rows = container.querySelectorAll('ol > li');
		expect(rows).toHaveLength(4);
		expect(
			[...rows[1].querySelectorAll('[data-node]')].map((node) => node.getAttribute('data-node'))
		).toEqual(['ocr', 'pages']);
		// What is uncertain is open.
		const judge = container.querySelector('[data-node="judge"]') as HTMLDetailsElement;
		expect(judge.open).toBe(true);
		expect(await within(judge).findByText('contact: the name is only similar')).toBeTruthy();
	});

	it('tells the tokens behind the info icon and shows the prompt', async () => {
		render(DocumentLog, { document, graph, manageable: true, onreprocess: vi.fn() });
		const info = await screen.findByRole('button', { name: m.tokens_details() });
		await fireEvent.mouseEnter(info);
		const tooltip = screen.getByRole('tooltip');
		expect(within(tooltip).getByText(m.tokens_input())).toBeTruthy();
		expect(tooltip.textContent).toContain('2,318');
		await userEvent.click(screen.getByRole('button', { name: m.prompt_open() }));
		expect(await screen.findByText('You read one document.')).toBeTruthy();
		await userEvent.click(screen.getByRole('button', { name: m.prompt_answer() }));
		expect(screen.getByText('{"contact": null}')).toBeTruthy();
	});

	it('shows only the states to someone who may not read the log', () => {
		render(DocumentLog, { document, graph, manageable: false, onreprocess: vi.fn() });
		expect(fetchMock).not.toHaveBeenCalled();
		expect(screen.getAllByText(m.log_owner_only()).length).toBeGreaterThan(0);
	});
});
