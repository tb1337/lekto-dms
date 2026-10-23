import { render, screen, waitFor, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { goto } from '$app/navigation';
import type { components } from '#lib/api/schema.ts';
import { desktop } from '#lib/desktop.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import type { GraphNode } from '#lib/pipeline.ts';
import { goTo } from '#lib/testing/page-state.svelte.ts';
import DocumentProcessing from './DocumentProcessing.svelte';

type Document = components['schemas']['DocumentDetails'];

vi.mock('$app/navigation', () => ({
	goto: vi.fn(async (href: string) =>
		(await import('#lib/testing/page-state.svelte.ts')).goTo(href, { id: 'doc-1' })
	)
}));
vi.mock('$app/state', async () => ({
	page: (await import('#lib/testing/page-state.svelte.ts')).testPage
}));

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
	{ node: 'signal_neighbours', requires: ['ocr'] },
	{ node: 'judge', requires: ['signal_llm', 'signal_neighbours'] },
	{ node: 'file', requires: ['judge'] }
];

function state(node: string, outcome: string | null, status = 'done') {
	return {
		node,
		status,
		outcome,
		started_at: status === 'waiting' ? null : '2026-10-13T09:14:22Z',
		finished_at: status === 'done' ? '2026-10-13T09:14:28Z' : null
	};
}

function documentAt(run: number, status: string, nodes: unknown[]): Document {
	return {
		id: 'doc-1',
		space_id: 's-mine',
		processing: { status, run, nodes }
	} as unknown as Document;
}

const document = documentAt(1, 'review', [
	state('receive', 'ok'),
	state('ocr', 'ok'),
	state('pages', 'ok'),
	state('signal_llm', 'ok'),
	state('signal_neighbours', 'ok'),
	state('judge', 'uncertain'),
	state('file', null, 'waiting')
]);

const proposed = {
	node: 'signal_llm',
	run: 1,
	outcome: 'ok',
	reason: null,
	confidence: null,
	model_version: 'qwen3:8b',
	input: {},
	output: {
		proposal: {
			sender: { value: 'Schwälmer Brotladen' },
			recipient: 'Anna Leider',
			document_type: 'Lohnabrechnung'
		},
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
	output: {
		fields: [
			{
				field: 'contact',
				outcome: 'uncertain',
				confidence: 0.62,
				candidates: [
					{
						value: null,
						label: 'Schwälmer Brotladen',
						contradicted: true,
						sources: [{ signal: 'signal_llm', names: true }]
					},
					{
						value: 'c-juko',
						label: 'JUKO Marburg e.V.',
						contradicted: false,
						sources: [{ signal: 'signal_neighbours', names: true, votes: 4, of: 5 }]
					}
				]
			}
		]
	},
	duration_ms: 12
};

const exchange = {
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
};

function serve(log: unknown[], exchanges: Record<string, unknown[]> = {}) {
	fetchMock.mockImplementation(async (request) => {
		const path = new URL(request.url).pathname;
		if (path.endsWith('/log')) return json(log);
		const node = path.split('/exchanges/')[1];
		return json(node ? (exchanges[node] ?? []) : []);
	});
}

function show(props: Partial<Parameters<typeof render<typeof DocumentProcessing>>[1]> = {}) {
	return render(DocumentProcessing, {
		document,
		graph,
		manageable: true,
		onreprocess: vi.fn(),
		...props
	} as never);
}

/** The card of `node`. */
function card(container: HTMLElement, node: string): HTMLElement {
	return container.querySelector(`button[data-node="${node}"]`) as HTMLElement;
}

/** Opens an info icon's box; it lies in a layer over the page, outside its column. */
async function openTip(button: HTMLElement): Promise<HTMLElement> {
	await userEvent.click(button);
	return waitFor(() => {
		const tip = globalThis.document.querySelector<HTMLElement>('[data-info-tip]');
		expect(tip).not.toBeNull();
		return tip!;
	});
}

beforeEach(() => {
	fetchMock.mockReset();
	serve([proposed, judged], { signal_llm: [exchange] });
	vi.stubGlobal('fetch', fetchMock);
	vi.mocked(goto).mockClear();
	goTo('/ui/documents/doc-1?tab=processing', { id: 'doc-1' });
	desktop.override(true);
});

afterEach(() => {
	vi.unstubAllGlobals();
	desktop.override(null);
	// A dialog makes the page unclickable until it has closed; the next test must not wait.
	window.document.body.style.pointerEvents = '';
});

describe('DocumentProcessing', () => {
	it('tells at a glance where the run stands, with the band and the counts', async () => {
		show();
		const head = screen.getByRole('heading', { level: 2, name: m.run_review({ run: 1 }) });
		expect(head).toBeTruthy();
		expect(await screen.findByText(m.run_why_fields({ fields: m.field_contact() }))).toBeTruthy();
		// The way to the review in the document tab.
		const review = screen.getByRole('link', { name: m.run_to_review() });
		expect(review.getAttribute('href')).toBe('/ui/documents/doc-1?left=pages&right=form');
		const band = screen.getByRole('img', { name: new RegExp(m.run_band({ run: 1 })) });
		expect(band.getAttribute('aria-label')).toContain(`${m.node_judge()} ${m.outcome_uncertain()}`);
		const counts = screen.getByRole('list', { name: m.run_counts() });
		expect(counts.textContent).toContain(`5 ${m.run_count_done()}`);
		expect(counts.textContent).toContain(`1 ${m.run_count_uncertain()}`);
		expect(counts.textContent).toContain(`1 ${m.run_count_waiting_one()}`);
	});

	it('shows the steps in their phases and opens what keeps the run, as the log did', async () => {
		const { container } = show();
		expect(screen.getByRole('heading', { name: new RegExp(m.phase_recognise()) })).toBeTruthy();
		const model = card(container, 'signal_llm');
		// Durations without a space between number and unit.
		expect(model.textContent).toContain('6s');
		expect(
			await within(model).findByText(
				`${m.summary_from_to({ sender: 'Schwälmer Brotladen', recipient: 'Anna Leider' })} · Lohnabrechnung`
			)
		).toBeTruthy();
		const judge = card(container, 'judge');
		expect(judge.getAttribute('aria-expanded')).toBe('true');
		const panel = container.querySelector('#step-details') as HTMLElement;
		expect(await within(panel).findByText('contact: the name is only similar')).toBeTruthy();
		expect(card(container, 'file').textContent).toContain(m.summary_file_waits());
	});

	it('opens and closes a step through the link', async () => {
		const { container } = show();
		await userEvent.click(card(container, 'signal_llm'));
		expect(goto).toHaveBeenCalledWith('/ui/documents/doc-1?tab=processing&step=signal_llm', {
			replace: true,
			reset: false
		});
		await waitFor(() =>
			expect(card(container, 'signal_llm').getAttribute('aria-expanded')).toBe('true')
		);
		await userEvent.click(screen.getByRole('button', { name: m.run_close_details() }));
		await waitFor(() => expect(container.querySelector('#step-details')).toBeNull());
		// Closed is closed: the uncertain verdict does not open again by itself.
		expect(card(container, 'judge').getAttribute('aria-expanded')).toBe('false');
	});

	it('tells the tokens behind the info icon and shows the prompt', async () => {
		const { container } = show();
		await userEvent.click(card(container, 'signal_llm'));
		const panel = await waitFor(() => container.querySelector('#step-details') as HTMLElement);
		const tooltip = await openTip(
			await within(panel).findByRole('button', { name: m.tokens_details() })
		);
		expect(tooltip.textContent).toContain('2,318');
		expect(panel.textContent).toMatch(/\d · qwen3:8b/);
		await userEvent.click(within(panel).getByRole('button', { name: m.prompt_open() }));
		expect(await screen.findByText('You read one document.')).toBeTruthy();
		await userEvent.keyboard('{Escape}');
	});

	it('runs the steps down a line on a narrower screen, opening a step below its card', async () => {
		desktop.override(false);
		const { container } = show();
		const judge = card(container, 'judge');
		expect(judge.getAttribute('aria-controls')).toBe('step-details-judge');
		const panel = container.querySelector('#step-details-judge') as HTMLElement;
		expect(await within(panel).findByText('contact: the name is only similar')).toBeTruthy();
	});

	it('shows one run at a time and tells what changed since the run before', async () => {
		// Run 2 started again at the verdict: the model's proposal is the one of run 1.
		const decided = (contact: string) => ({
			fields: [{ field: 'contact', outcome: 'ok', confidence: 1, value: contact }]
		});
		const first = { ...judged, output: decided('c-juko'), outcome: 'ok', reason: null };
		const second = { ...first, run: 2, output: decided('c-bakery') };
		const filed = { ...proposed, node: 'file', run: 2, output: {} };
		serve([proposed, first, second, filed]);
		const current = documentAt(2, 'completed', [
			state('receive', 'ok'),
			state('ocr', 'ok'),
			state('pages', 'ok'),
			state('signal_llm', 'ok'),
			state('signal_neighbours', 'ok'),
			state('judge', 'ok'),
			state('file', 'ok')
		]);
		const { container } = show({ document: current });
		expect(screen.getByRole('heading', { level: 2, name: m.run_through({ run: 2 }) })).toBeTruthy();
		expect(await screen.findByText(new RegExp(m.run_since({ run: 1 })))).toBeTruthy();
		expect(
			within(card(container, 'signal_llm')).getByText(new RegExp(m.log_from_run({ run: 1 })))
		).toBeTruthy();
		const earlier = screen.getByRole('button', { name: new RegExp(m.log_run({ run: 1 })) });
		await userEvent.click(earlier);
		expect(earlier.getAttribute('aria-pressed')).toBe('true');
		expect(
			screen.getByRole('heading', { name: `${m.processing_steps()} · ${m.log_run({ run: 1 })}` })
		).toBeTruthy();
		expect(screen.queryByText(new RegExp(m.run_since({ run: 1 })))).toBeNull();
	});

	it('tells a step a person confirmed as it was', async () => {
		const confirmed = {
			...judged,
			run: 2,
			outcome: 'ok',
			reason: null,
			model_version: 'person',
			output: { confirmed_by: 'u-tobi', outcome_before: 'uncertain' }
		};
		serve([proposed, judged, confirmed]);
		const current = documentAt(2, 'completed', [
			state('receive', 'ok'),
			state('ocr', 'ok'),
			state('pages', 'ok'),
			state('signal_llm', 'ok'),
			state('signal_neighbours', 'ok'),
			state('judge', 'ok'),
			state('file', 'ok')
		]);
		const { container } = show({ document: current });
		const judge = card(container, 'judge');
		const name = m.space_named_someone();
		expect(await within(judge).findByText(m.summary_overruled_confirmed({ name }))).toBeTruthy();
		await userEvent.click(judge);
		const panel = await waitFor(() => container.querySelector('#step-details') as HTMLElement);
		expect(within(panel).getByText(m.processing_overruled_confirmed({ name }))).toBeTruthy();
		// A person's confirmation has no prompt of its own.
		expect(within(panel).queryByRole('button', { name: m.prompt_open() })).toBeNull();
	});

	it('shows only the states to someone who may not read the log', async () => {
		const { container } = show({ manageable: false });
		expect(fetchMock).not.toHaveBeenCalled();
		const panel = container.querySelector('#step-details') as HTMLElement;
		expect(within(panel).getByText(m.log_editors_only())).toBeTruthy();
	});
});
