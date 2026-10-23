import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import type { GraphNode, Node, NodeState } from '#lib/pipeline.ts';
import { changesOf, headlineOf } from './run-summary.ts';
import { stepsOf } from './steps.ts';

type LogEntry = components['schemas']['LogEntry'];
type ProcessingStatus = components['schemas']['ProcessingStatus'];

const TOBI = 'u-tobi';
const ANNA = 'u-anna';
const MINE = 's-mine';
const ANNAS = 's-anna';
const JUKO = 'c-juko';
const BAKERY = 'c-bakery';

const lookup = {
	contacts: [
		{ id: JUKO, name: 'JUKO Marburg e.V.' },
		{ id: BAKERY, name: 'Schwälmer Brotladen' }
	],
	documentTypes: [],
	tags: [],
	fields: [],
	spaces: [
		{
			id: MINE,
			name: 'Personal',
			personal_of: TOBI,
			role: 'edit',
			members: [{ user_id: TOBI, role: 'edit', username: 'tobi' }]
		}
	],
	users: [
		{ id: TOBI, username: 'tobi', role: 'user', personal_space_id: MINE },
		{
			id: ANNA,
			username: 'anna',
			display_name: 'Anna Leider',
			role: 'user',
			personal_space_id: ANNAS
		}
	]
} as unknown as Lookup;

const tobi = { id: TOBI, admin: false };

const graph: GraphNode[] = [
	{ node: 'receive', requires: [] },
	{ node: 'ocr', requires: ['receive'] },
	{ node: 'signal_llm', requires: ['ocr'] },
	{ node: 'judge', requires: ['signal_llm'] },
	{ node: 'fields', requires: ['judge'] },
	{ node: 'apply_rules', requires: ['fields'] },
	{ node: 'file', requires: ['apply_rules'] }
];
const NODES = graph.map((entry) => entry.node);

function entry(
	node: Node,
	run: number,
	outcome: LogEntry['outcome'] = 'ok',
	output: Record<string, unknown> = {},
	extra: Partial<LogEntry> = {}
): LogEntry {
	return {
		node,
		run,
		outcome,
		reason: outcome === 'ok' ? null : 'why',
		confidence: null,
		model_version: 'model',
		input: {},
		output,
		pipeline_version: 'test',
		started_at: '2026-10-23T09:00:00Z',
		duration_ms: 1000,
		...extra
	};
}

function state(node: Node, outcome: NodeState['outcome'], status: NodeState['status'] = 'done') {
	return {
		node,
		status,
		outcome,
		started_at: status === 'waiting' ? null : '2026-10-23T09:00:00Z',
		finished_at: status === 'done' ? '2026-10-23T09:00:01Z' : null
	};
}

function steps(states: NodeState[], log: LogEntry[], run: number, status: ProcessingStatus) {
	return stepsOf(NODES, log, new Map(states.map((entry) => [entry.node, entry])), {
		number: run,
		current: true,
		again: new Set(),
		status
	});
}

const spaceOpen = {
	fields: [
		{ field: 'contact', outcome: 'ok', confidence: 1, value: BAKERY },
		{
			field: 'space',
			outcome: 'uncertain',
			confidence: 0.6,
			suggestion: ANNAS,
			unseen_by: []
		}
	],
	persons: [{ user_id: ANNA, strength: 'hard' }]
};

describe('headlineOf', () => {
	it('tells where a running run is', () => {
		const shown = steps(
			[state('receive', 'ok'), state('ocr', null, 'running')],
			[entry('receive', 1)],
			1,
			'processing'
		);
		const headline = headlineOf(
			{ number: 1, current: true, status: 'processing' },
			shown,
			MINE,
			lookup,
			tobi
		);
		expect(headline).toMatchObject({ tone: 'running', action: null });
		expect(headline.title).toBe(m.run_running_at({ run: 1, steps: m.node_ocr() }));
	});

	it('tells why a run stops before filing, with the suggestion and its evidence', () => {
		const log = [entry('judge', 3, 'uncertain', spaceOpen)];
		const shown = steps(
			[state('judge', 'uncertain'), state('file', null, 'waiting')],
			log,
			3,
			'review'
		);
		const headline = headlineOf(
			{ number: 3, current: true, status: 'review' },
			shown,
			MINE,
			lookup,
			tobi
		);
		expect(headline.title).toBe(m.run_review({ run: 3 }));
		expect(headline.action).toBe('filing');
		expect(headline.detail).toBe(
			[
				m.run_why_space({ choice: m.move_hand_over({ name: 'Anna Leider' }) }),
				m.run_why_evidence({ name: 'Anna Leider' })
			].join(' ')
		);
		// The same run, looked at later: it stopped then, nothing waits for anyone now.
		const past = headlineOf(
			{ number: 3, current: false, status: 'review' },
			shown,
			MINE,
			lookup,
			tobi
		);
		expect(past.title).toBe(m.run_review_past({ run: 3 }));
		expect(past.action).toBeNull();
	});

	it('names uncertain fields and asks for the review', () => {
		const output = { fields: [{ field: 'document_date', outcome: 'uncertain', confidence: 0 }] };
		const shown = steps(
			[state('judge', 'uncertain')],
			[entry('judge', 1, 'uncertain', output)],
			1,
			'review'
		);
		const headline = headlineOf(
			{ number: 1, current: true, status: 'review' },
			shown,
			MINE,
			lookup,
			tobi
		);
		expect(headline.detail).toBe(m.run_why_fields({ fields: m.field_date() }));
		expect(headline.action).toBe('review');
	});

	it('tells a review a rule forces in a sentence of its own', () => {
		const output = {
			fields: [{ field: 'review', outcome: 'uncertain', confidence: 0, reason: "rule 'x': check" }]
		};
		const shown = steps(
			[state('apply_rules', 'uncertain'), state('file', null, 'waiting')],
			[entry('apply_rules', 2, 'uncertain', output)],
			2,
			'review'
		);
		const headline = headlineOf(
			{ number: 2, current: true, status: 'review' },
			shown,
			MINE,
			lookup,
			tobi
		);
		expect(headline.detail).toBe(m.run_why_rule_review());
	});

	it('tells where a run failed and why', () => {
		const log = [entry('ocr', 1, 'failed', {}, { reason: 'Ghostscript gave up' })];
		const shown = steps([state('ocr', 'failed')], log, 1, 'failed');
		const headline = headlineOf(
			{ number: 1, current: true, status: 'failed' },
			shown,
			MINE,
			lookup,
			tobi
		);
		expect(headline).toEqual({
			tone: 'red',
			title: m.run_failed({ run: 1, steps: m.node_ocr() }),
			detail: 'Ghostscript gave up',
			action: 'reprocess'
		});
	});

	it('tells whether a run went through by itself or after a person', () => {
		const clean = steps(
			NODES.map((node) => state(node, 'ok')),
			NODES.map((node) => entry(node, 1)),
			1,
			'completed'
		);
		const run = { number: 1, current: true, status: 'completed' as const };
		expect(headlineOf(run, clean, MINE, lookup, tobi).title).toBe(m.run_through({ run: 1 }));
		const confirmed = entry('judge', 2, 'ok', { confirmed_by: TOBI, outcome_before: 'uncertain' });
		const after = steps(
			NODES.map((node) => state(node, 'ok')),
			[entry('judge', 1, 'uncertain'), { ...confirmed, model_version: 'person' }],
			2,
			'completed'
		);
		expect(headlineOf({ ...run, number: 2 }, after, MINE, lookup, tobi).title).toBe(
			m.run_through_confirmed({ run: 2, name: 'tobi' })
		);
	});
});

describe('changesOf', () => {
	const decided = (contact: string) => ({
		fields: [
			{ field: 'contact', outcome: 'ok', value: contact },
			{ field: 'space', outcome: 'uncertain', suggestion: ANNAS }
		]
	});

	it('tells the decided values that changed since the run before', () => {
		const log = [
			entry('ocr', 2, 'uncertain', { pdfa: false }),
			entry('judge', 2, 'uncertain', decided(JUKO)),
			entry('ocr', 3, 'ok', { pdfa: true }),
			entry('judge', 3, 'uncertain', decided(BAKERY))
		];
		expect(changesOf(log, graph, 3, [3, 2, 1], lookup)).toEqual({
			since: 2,
			items: [
				m.run_change({
					field: m.field_contact(),
					before: 'JUKO Marburg e.V.',
					after: 'Schwälmer Brotladen'
				}),
				m.run_change_pdfa()
			]
		});
	});

	it('tells nothing for the first run, nor when nothing changed', () => {
		const log = [entry('judge', 1, 'ok', decided(JUKO)), entry('judge', 2, 'ok', decided(JUKO))];
		expect(changesOf(log, graph, 1, [2, 1], lookup)).toBeNull();
		expect(changesOf(log, graph, 2, [2, 1], lookup)).toBeNull();
	});
});
