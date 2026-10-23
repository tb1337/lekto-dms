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
		const band = screen.getByRole('group', { name: new RegExp(m.run_band({ run: 1 })) });
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
		// The focus goes back to the step's card, the close button went with the panel.
		await waitFor(() => expect(window.document.activeElement).toBe(card(container, 'signal_llm')));
		// Closed is closed: the uncertain verdict does not open again by itself.
		expect(card(container, 'judge').getAttribute('aria-expanded')).toBe('false');
		expect(card(container, 'judge').getAttribute('aria-controls')).toBeNull();
	});

	it('lights up a step in the band and at its card together, and opens it from the band', async () => {
		const { container } = show();
		const band = screen.getByRole('group', { name: new RegExp(m.run_band({ run: 1 })) });
		const segment = within(band).getByRole('button', {
			name: new RegExp(`^${m.node_signal_llm()}`)
		});
		const reading = () => container.querySelector('[data-band-reading]')?.textContent ?? '';
		// Without a step lit, the reading line tells the run's span.
		expect(reading()).toContain(m.run_band_span({ run: 1, start: '§', end: '§' }).split('§')[0]);
		await userEvent.hover(segment);
		// The card lights up, the segment too while the others step back, a bracket spans it, and
		// the reading line tells its state, name, time and what it did; nothing grows.
		expect(card(container, 'signal_llm').hasAttribute('data-highlighted')).toBe(true);
		expect(segment.hasAttribute('data-lit')).toBe(true);
		expect(segment.className).not.toMatch(/scale-/);
		const others = within(band)
			.getAllByRole('button')
			.filter((other) => other !== segment);
		expect(others.every((other) => other.className.includes('opacity-35'))).toBe(true);
		await waitFor(() => expect(container.querySelector('[data-band-bracket]')).not.toBeNull());
		expect(reading()).toContain(m.outcome_ok());
		expect(reading()).toContain(`${m.node_signal_llm()} · 6s`);
		expect(reading()).toContain('Schwälmer Brotladen');
		expect(reading()).toContain('→');
		await userEvent.unhover(segment);
		expect(card(container, 'signal_llm').hasAttribute('data-highlighted')).toBe(false);
		expect(container.querySelector('[data-band-bracket]')).toBeNull();
		// Pointing at a card lights up its segment.
		await userEvent.hover(card(container, 'ocr'));
		const ocr = within(band).getByRole('button', { name: new RegExp(`^${m.node_ocr()}`) });
		expect(ocr.hasAttribute('data-lit')).toBe(true);
		await userEvent.unhover(card(container, 'ocr'));
		// A click on the segment opens the step as its card does.
		await userEvent.click(segment);
		expect(goto).toHaveBeenCalledWith('/ui/documents/doc-1?tab=processing&step=signal_llm', {
			replace: true,
			reset: false
		});
		await waitFor(() =>
			expect(card(container, 'signal_llm').getAttribute('aria-expanded')).toBe('true')
		);
		expect(segment.getAttribute('aria-expanded')).toBe('true');
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

	it('tells which signal named what, without a column of results on a desktop', async () => {
		show();
		const matrix = await screen.findByRole('table');
		expect(within(matrix).getByText('Schwälmer Brotladen')).toBeTruthy();
		expect(
			within(matrix).getByRole('img', { name: `${m.node_signal_llm()}: ${m.matrix_suggests()}` })
		).toBeTruthy();
		// The neighbours name JUKO without a proof in the text: another value, not against it
		// (the 0.5.0 contact rule).
		expect(
			within(matrix).getByRole('img', {
				name: `${m.node_signal_neighbours()}: ${m.matrix_other()}`
			})
		).toBeTruthy();
		expect(within(matrix).queryByText(m.matrix_chip_question())).toBeNull();
	});

	it('runs the steps down a line on a narrower screen, opening a step below its card', async () => {
		desktop.override(false);
		const { container } = show();
		const judge = card(container, 'judge');
		expect(judge.getAttribute('aria-controls')).toBe('step-details-judge');
		const panel = container.querySelector('#step-details-judge') as HTMLElement;
		expect(await within(panel).findByText('contact: the name is only similar')).toBeTruthy();
		// The matrix with a word for each value.
		expect(await screen.findByText(m.matrix_chip_question())).toBeTruthy();
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

	it('ends the first run in the runs list as the document keeps it', async () => {
		desktop.override(true);
		// The log of run 1 stopped for review; the document keeps that its first run failed.
		const again = { ...judged, run: 2, outcome: 'ok', reason: null };
		serve([proposed, judged, again], { signal_llm: [exchange] });
		const runs = (first_lane: Document['first_lane']) =>
			({
				...document,
				first_lane,
				processing: { ...document.processing, run: 2 }
			}) as unknown as Document;
		const first = () =>
			within(screen.getByRole('region', { name: m.log_runs() })).getByRole('button', {
				name: new RegExp(m.log_run({ run: 1 }))
			});

		const { unmount } = show({ document: runs('red') });
		expect(await screen.findByText(`${m.processing_steps()} · ${m.log_run({ run: 2 })}`));
		await waitFor(() => expect(first().textContent).toContain(m.outcome_failed()));
		unmount();

		show({ document: runs(null) });
		await waitFor(() => expect(first().textContent).toContain(m.lane_yellow()));
	});

	it('tells a step a person confirmed as it was', async () => {
		const confirmed = {
			...judged,
			run: 2,
			outcome: 'ok',
			reason: null,
			model_version: 'person',
			output: {
				confirmed_by: 'u-tobi',
				outcome_before: 'uncertain',
				accepted: [],
				entered: ['contact'],
				kept: []
			}
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
		current.contact_id = 'c-juko';
		const { container } = show({ document: current });
		const judge = card(container, 'judge');
		const name = m.space_named_someone();
		expect(await within(judge).findByText(m.summary_overruled_confirmed({ name }))).toBeTruthy();
		await userEvent.click(judge);
		const panel = await waitFor(() => container.querySelector('#step-details') as HTMLElement);
		expect(within(panel).getByText(m.processing_overruled_confirmed({ name }))).toBeTruthy();
		// A person's confirmation has no prompt of its own.
		expect(within(panel).queryByRole('button', { name: m.prompt_open() })).toBeNull();
		// Which signal named what stays: the verdict the confirmation decided, decided by hand.
		const matrix = await screen.findByRole('table');
		expect(within(matrix).getByText('JUKO Marburg e.V.')).toBeTruthy();
		expect(within(matrix).queryByRole('img', { name: m.matrix_open() })).toBeNull();
	});

	it('tells no times of a later run it cannot tell apart from an earlier one', async () => {
		// Run 2 without the log (a reader): receiving is run 1's, hours before the rest.
		const later = documentAt(2, 'completed', [
			{
				...state('receive', 'ok'),
				started_at: '2026-10-13T01:00:00Z',
				finished_at: '2026-10-13T01:00:01Z'
			},
			state('ocr', 'ok'),
			state('pages', 'ok'),
			state('signal_llm', 'ok'),
			state('signal_neighbours', 'ok'),
			state('judge', 'ok'),
			state('file', 'ok')
		]);
		show({ document: later, manageable: false });
		const read = screen.getByRole('heading', { name: new RegExp(m.phase_read()) });
		expect(read.textContent).not.toMatch(/\d+(h|m|s)/);
		const band = screen.getByRole('group', { name: new RegExp(m.run_band({ run: 2 })) });
		expect(band.getAttribute('aria-label')).not.toMatch(/\d+h/);
	});

	it('shows only the states to someone who may not read the log', async () => {
		const { container } = show({ manageable: false });
		expect(fetchMock).not.toHaveBeenCalled();
		const panel = container.querySelector('#step-details') as HTMLElement;
		expect(within(panel).getByText(m.log_editors_only())).toBeTruthy();
		expect(screen.queryByRole('table')).toBeNull();
	});
});
