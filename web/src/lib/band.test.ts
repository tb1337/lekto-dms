import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { GraphNode, Node, NodeState } from '#lib/pipeline.ts';
import {
	bandOf,
	CARRIED_BASIS,
	CARRIED_PHASE,
	groupWidths,
	labelFor,
	MIN_OWN_PHASE,
	MIN_PHASE,
	minimumsOf,
	STEP_BASIS,
	textWidth,
	widthsOf,
	type BandPhase
} from './band.ts';
import { stepsOf } from './steps.ts';

type LogEntry = components['schemas']['LogEntry'];

const graph: GraphNode[] = [
	{ node: 'receive', requires: [], waits_for: [] },
	{ node: 'ocr', requires: ['receive'], waits_for: [] },
	{ node: 'pages', requires: ['receive'], waits_for: [] },
	{ node: 'parse', requires: ['ocr'], waits_for: [] },
	{ node: 'signal_llm', requires: ['parse'], waits_for: [] },
	{ node: 'signal_classifier', requires: ['parse'], waits_for: [] },
	{ node: 'judge', requires: ['signal_llm', 'signal_classifier'], waits_for: [] },
	{ node: 'fields', requires: ['judge'], waits_for: [] },
	{ node: 'apply_rules', requires: ['fields'], waits_for: [] },
	{ node: 'file', requires: ['apply_rules'], waits_for: [] }
];

const base = Date.UTC(2026, 9, 23, 9, 0, 0);
const at = (offset: number) => new Date(base + offset * 1000);

/** A node that ran from `start` for `seconds` (seconds after 09:00:00). */
function ran(node: Node, start: number, seconds: number, outcome: NodeState['outcome'] = 'ok') {
	return {
		node,
		status: 'done' as const,
		outcome,
		started_at: at(start).toISOString(),
		finished_at: at(start + seconds).toISOString()
	};
}

function waiting(node: Node): NodeState {
	return { node, status: 'waiting', outcome: null, started_at: null, finished_at: null };
}

function entry(node: Node, run: number, extra: Partial<LogEntry> = {}): LogEntry {
	return {
		node,
		run,
		outcome: 'ok',
		reason: null,
		confidence: null,
		model_version: null,
		input: {},
		output: {},
		pipeline_version: 'test',
		started_at: '2026-10-23T09:00:00Z',
		duration_ms: 100,
		...extra
	};
}

function stepsFrom(states: NodeState[], log: LogEntry[] = [], run = 1) {
	return stepsOf(
		graph.map((node) => node.node),
		log,
		new Map(states.map((state) => [state.node, state])),
		{ number: run, current: true, again: new Set(), status: 'review' }
	);
}

const nodesOf = (phase: BandPhase) =>
	phase.groups.map((group) => group.steps.map((step) => step.node));
const grows = (phase: BandPhase) => phase.groups.reduce((sum, group) => sum + group.grow, 0);

describe('widthsOf', () => {
	it('splits the bar by weight, keeping a minimum for a light phase', () => {
		const parts = widthsOf([4, 22, 11, 0.6]);
		expect(parts.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1);
		expect(parts[3]).toBeCloseTo(MIN_PHASE);
		expect(parts[1]).toBeGreaterThan(parts[2]);
		expect(parts[2]).toBeGreaterThan(parts[0]);
	});

	it('keeps exactly its minimum for a phase weighing nothing of its own', () => {
		const parts = widthsOf([null, 30, 10], [0.08, 0.06, 0.06]);
		expect(parts[0]).toBeCloseTo(0.08);
		expect(parts[1] / parts[2]).toBeCloseTo(3);
		expect(parts.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1);
	});

	it('gives equal parts without any weight, and shrinks minimums that do not fit', () => {
		expect(widthsOf([0, 0])).toEqual([0.5, 0.5]);
		expect(widthsOf([])).toEqual([]);
		expect(widthsOf([1, 1], [0.8, 0.8])).toEqual([0.5, 0.5]);
	});
});

describe('minimumsOf', () => {
	const phases = [
		{ phase: 'read', weight: null, groups: [], carried: true, from: 1 },
		{ phase: 'decide', weight: 3, groups: [], carried: false, from: null }
	] satisfies BandPhase[];

	it('keeps room for the label and a part of its own', () => {
		expect(minimumsOf(phases, 1000, [10, 120])).toEqual([CARRIED_PHASE, 0.12]);
		expect(minimumsOf(phases, 1000, [0, 0])).toEqual([CARRIED_PHASE, MIN_OWN_PHASE]);
	});

	it('falls back to the plain minimum while the width is not known', () => {
		expect(minimumsOf(phases, 0, [10, 120])).toEqual([MIN_PHASE, MIN_PHASE]);
	});
});

describe('groupWidths', () => {
	it('gives each group its basis and the rest by how it grows', () => {
		const groups = [
			{ steps: [], grow: 0, basis: 10 },
			{ steps: [], grow: 0.75, basis: 4 },
			{ steps: [], grow: 0.25, basis: 4 }
		];
		const sizes = groupWidths(122, groups);
		// 122 - 2 gaps of 2 - bases 18 = 100 to share.
		expect(sizes).toEqual([10, 79, 29]);
	});

	it('fills only part of the room when the groups grow by less than 1, as flexbox does', () => {
		const sizes = groupWidths(100, [{ steps: [], grow: 0.1, basis: 0 }]);
		expect(sizes).toEqual([10]);
	});
});

describe('labelFor', () => {
	it('puts the step with its time, the step alone, or nothing; never cut', () => {
		const name = 'Sprachmodell';
		expect(labelFor(name, '22s', 400)).toBe('Sprachmodell 22s');
		expect(labelFor(name, '22s', textWidth(name, 11) + 16)).toBe('Sprachmodell');
		expect(labelFor(name, '22s', 40)).toBeNull();
	});
});

describe('bandOf', () => {
	it('lays out a first run by its times, the steps side by side on top of each other', () => {
		const steps = stepsFrom([
			ran('receive', 0, 0.1),
			ran('ocr', 0.1, 4),
			ran('pages', 0.1, 0.3),
			ran('parse', 4.1, 0.1),
			ran('signal_llm', 4.2, 22),
			ran('signal_classifier', 4.2, 2),
			ran('judge', 26.2, 3, 'uncertain'),
			ran('fields', 29.2, 8),
			ran('apply_rules', 37.2, 0.6),
			waiting('file')
		]);
		const band = bandOf(steps, graph, at(40));
		expect(band.map((phase) => phase.phase)).toEqual(['read', 'recognise', 'decide', 'file']);
		const [read, recognise, decide, file] = band;
		expect(nodesOf(read)).toEqual([['receive'], ['ocr', 'pages'], ['parse']]);
		expect(read.groups[1].steps[1].share).toBeCloseTo(0.3 / 4);
		expect(read.weight).toBeCloseTo(4.2);
		expect(nodesOf(recognise)).toEqual([['signal_llm', 'signal_classifier']]);
		expect(recognise.weight).toBe(22);
		expect(decide.groups[0].steps[0].tone).toBe('yellow');
		// Within a phase the groups grow by their time, together exactly the phase.
		for (const phase of band) expect(grows(phase)).toBeCloseTo(1);
		expect(read.groups.every((group) => group.basis === STEP_BASIS)).toBe(true);
		// The waiting filing stands for a short time of its own.
		expect(file.groups[1].steps[0]).toMatchObject({ node: 'file', tone: 'waiting', seconds: null });
		expect(file.groups[1].grow).toBeGreaterThan(file.groups[0].grow);
	});

	it('draws the steps a review run kept muted, a few pixels wide beside its own', () => {
		// Run 3 started again at the OCR: receiving and the page images are run 1's.
		const log = [entry('receive', 1), entry('pages', 1), entry('ocr', 3), entry('parse', 3)];
		const steps = stepsFrom(
			[
				ran('receive', -3600, 0.1),
				ran('ocr', 0, 4),
				ran('pages', -3600, 0.3),
				ran('parse', 4, 0.1),
				ran('signal_llm', 4.1, 22),
				ran('signal_classifier', 4.1, 2),
				ran('judge', 26.1, 3, 'uncertain'),
				ran('fields', 29.1, 8),
				ran('apply_rules', 37.1, 0.6),
				waiting('file')
			],
			log,
			3
		);
		const [read] = bandOf(steps, graph, at(40));
		expect(nodesOf(read)).toEqual([['receive'], ['ocr', 'pages'], ['parse']]);
		const [receiving, reading, parsing] = read.groups;
		expect(receiving).toMatchObject({ grow: 0, basis: CARRIED_BASIS });
		expect(receiving.steps[0]).toMatchObject({ tone: 'carried', from: 1, seconds: null });
		expect(reading.steps[1]).toMatchObject({ node: 'pages', tone: 'carried', share: 0.2 });
		// The run's own time only: the hour before does not count.
		expect(read.weight).toBeCloseTo(4.1);
		expect(reading.grow + parsing.grow).toBeCloseTo(1);
		expect(read.carried).toBe(false);
	});

	it('shows every step alike for a run that only filed after a confirmation', () => {
		// Run 4: a person confirmed the verdict of run 3; only the rules and the filing ran.
		const log = [
			entry('receive', 1),
			entry('pages', 1),
			entry('ocr', 3),
			entry('parse', 3),
			entry('signal_llm', 3),
			entry('signal_classifier', 3),
			entry('judge', 3, { outcome: 'uncertain', reason: 'space' }),
			entry('fields', 3),
			entry('judge', 4, {
				model_version: 'person',
				output: { outcome_before: 'uncertain', confirmed_by: 'u1' }
			}),
			entry('apply_rules', 4),
			entry('file', 4)
		];
		const steps = stepsFrom(
			[
				ran('receive', -7200, 0.1),
				ran('ocr', -60, 4),
				ran('pages', -7200, 0.3),
				ran('parse', -56, 0.1),
				ran('signal_llm', -55, 22),
				ran('signal_classifier', -55, 2),
				ran('judge', 0, 0),
				ran('fields', -30, 8),
				ran('apply_rules', 0.1, 0.1),
				ran('file', 0.2, 0.2)
			],
			log,
			4
		);
		const band = bandOf(steps, graph, at(1));
		const [read, recognise, decide, file] = band;
		expect(read).toMatchObject({ carried: true, from: null, weight: 3 });
		expect(recognise).toMatchObject({ carried: true, from: 3, weight: 1 });
		expect(decide).toMatchObject({ carried: false, weight: 2 });
		expect(file.weight).toBe(2);
		// No times: every group alike, nothing a few pixels, nothing left blank.
		for (const phase of band)
			for (const group of phase.groups) expect(group).toMatchObject({ grow: 1, basis: 0 });
		const judge = decide.groups[0].steps[0];
		expect(judge).toMatchObject({ node: 'judge', tone: 'green', overruled: 'confirmed' });
		expect(decide.groups[1].steps[0]).toMatchObject({ node: 'fields', tone: 'carried', from: 3 });
		expect(file.groups.map((group) => group.steps[0].seconds)).toEqual([null, null]);
	});

	it('keeps a phase the run kept whole at a small part of its own while it tells times', () => {
		// Run 2 started again at the verdict: reading and recognising are run 1's.
		const log = [entry('receive', 1), entry('ocr', 1), entry('signal_llm', 1)];
		const steps = stepsFrom(
			[ran('receive', 0, 0.1), ran('ocr', 0.1, 4), ran('signal_llm', 5, 20), ran('judge', 60, 3)],
			log,
			2
		);
		const band = bandOf(steps, graph, at(70));
		expect(band.map((phase) => [phase.phase, phase.carried, phase.weight])).toEqual([
			['read', true, null],
			['recognise', true, null],
			['decide', false, 3]
		]);
		expect(band[0].groups.map((group) => group.grow)).toEqual([1, 1]);
		expect(band[0].from).toBe(1);
	});

	it('marks the failed step red and the steps that did not get to run as waiting', () => {
		const steps = stepsFrom([
			ran('receive', 0, 0.1),
			ran('ocr', 0.1, 6, 'failed'),
			ran('pages', 0.1, 0.4),
			waiting('parse')
		]);
		const [read] = bandOf(steps, graph, at(10));
		expect(read.groups[1].steps.map((step) => [step.node, step.tone])).toEqual([
			['ocr', 'red'],
			['pages', 'green']
		]);
		expect(read.groups[2].steps[0].tone).toBe('waiting');
	});

	it('times a running step by the clock', () => {
		const steps = stepsFrom([
			ran('receive', 0, 0.1),
			ran('ocr', 0.1, 4),
			ran('parse', 4.1, 0.1),
			{
				node: 'signal_llm',
				status: 'running',
				outcome: null,
				started_at: at(4.2).toISOString(),
				finished_at: null
			}
		]);
		const band = bandOf(steps, graph, at(14.2));
		const recognise = band.find((phase) => phase.phase === 'recognise');
		expect(recognise?.groups[0].steps[0]).toMatchObject({ tone: 'running', seconds: 10 });
		expect(recognise?.weight).toBe(10);
	});

	it('tells only how the steps stand while it is not known which ones the run kept', () => {
		// Run 3 without its log: receiving is run 1's, hours earlier; its time must not count.
		const steps = stepsFrom([ran('receive', -8 * 3600, 0.1), ran('ocr', 0.1, 4)], [], 3);
		const [read] = bandOf(steps, graph, at(10), false);
		expect(read.groups.flatMap((group) => group.steps.map((step) => step.seconds))).toEqual([
			null,
			null
		]);
		expect(read.groups.map((group) => group.grow)).toEqual([1, 1]);
		expect(read.weight).toBe(2);
	});
});
