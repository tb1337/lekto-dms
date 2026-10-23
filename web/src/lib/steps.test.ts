import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { Node, NodeState } from '#lib/pipeline.ts';
import { countsOf, phaseSeconds, phasesOf, stepsOf, stuck } from './steps.ts';

type LogEntry = components['schemas']['LogEntry'];
type ProcessingStatus = components['schemas']['ProcessingStatus'];

function state(node: Node, outcome: NodeState['outcome'], status: NodeState['status'] = 'done') {
	return {
		node,
		status,
		outcome,
		started_at: status === 'waiting' ? null : '2026-10-14T08:49:01Z',
		finished_at: status === 'done' ? '2026-10-14T08:49:05Z' : null
	};
}

function entry(node: Node, run: number, outcome: LogEntry['outcome'] = 'ok'): LogEntry {
	return {
		node,
		run,
		outcome,
		reason: outcome === 'ok' ? null : 'why',
		confidence: null,
		model_version: null,
		input: {},
		output: {},
		pipeline_version: 'test',
		started_at: '2026-10-14T08:49:01Z',
		duration_ms: 4000
	};
}

const NODES: Node[] = ['receive', 'ocr', 'signal_llm', 'judge', 'apply_rules', 'file'];

function current(
	states: NodeState[],
	log: LogEntry[] = [],
	run = 1,
	status: ProcessingStatus = 'processing'
) {
	return stepsOf(NODES, log, new Map(states.map((entry) => [entry.node, entry])), {
		number: run,
		current: true,
		again: new Set(),
		status
	});
}

function past(log: LogEntry[], run: number, status: ProcessingStatus) {
	return stepsOf(NODES, log, new Map(), { number: run, current: false, again: new Set(), status });
}

/** The entry the inbox writes for a step a person overruled. */
function confirmation(node: Node, run: number, before: LogEntry['outcome']): LogEntry {
	return {
		...entry(node, run),
		model_version: 'person',
		output: { confirmed_by: 'user-1', outcome_before: before }
	};
}

const judgeOf = (steps: ReturnType<typeof current>) => steps.find((step) => step.node === 'judge');

describe('stepsOf and phasesOf', () => {
	it('puts the steps of a run into the four phases, in graph order', () => {
		const steps = current(NODES.map((node) => state(node, 'ok')));
		expect(phasesOf(steps).map((group) => [group.phase, group.steps.map((s) => s.node)])).toEqual([
			['read', ['receive', 'ocr']],
			['recognise', ['signal_llm']],
			['decide', ['judge']],
			['file', ['apply_rules', 'file']]
		]);
	});

	it('reads a past run from its entries and keeps what it did not start again', () => {
		const log = [
			entry('receive', 1),
			entry('ocr', 1),
			entry('judge', 1, 'uncertain'),
			entry('judge', 2)
		];
		const steps = stepsOf(NODES, log, new Map(), {
			number: 2,
			current: false,
			again: new Set<Node>(['judge', 'apply_rules', 'file']),
			status: 'review'
		});
		const judge = steps.find((step) => step.node === 'judge');
		expect(judge?.state?.outcome).toBe('ok');
		expect(steps.find((step) => step.node === 'ocr')?.done.from).toBe(1);
		// Started again but never got to run.
		expect(steps.find((step) => step.node === 'file')?.state).toBeNull();
	});
});

describe('phaseSeconds', () => {
	it('runs from the first start to the last end, without what an earlier run did', () => {
		const states = [
			{
				...state('receive', 'ok'),
				started_at: '2026-10-14T08:00:00Z',
				finished_at: '2026-10-14T08:00:01Z'
			},
			{
				...state('ocr', 'ok'),
				started_at: '2026-10-14T09:00:00Z',
				finished_at: '2026-10-14T09:00:04.5Z'
			}
		];
		// Run 2 started at the OCR: the receiving is run 1's.
		const steps = current([...states], [entry('receive', 1), entry('ocr', 2)], 2);
		const read = steps.filter((step) => ['receive', 'ocr'].includes(step.node));
		expect(phaseSeconds(read, new Date())).toBe(4.5);
		expect(
			phaseSeconds(
				steps.filter((step) => step.node === 'file'),
				new Date()
			)
		).toBeNull();
	});

	it('counts a running step up to now', () => {
		const steps = current([state('signal_llm', null, 'running')]);
		const now = new Date('2026-10-14T08:49:11Z');
		expect(
			phaseSeconds(
				steps.filter((step) => step.node === 'signal_llm'),
				now
			)
		).toBe(10);
	});
});

describe('stuck', () => {
	it('names what failed, else what is uncertain', () => {
		const all = (overrides: Partial<Record<Node, NodeState>>) =>
			current(NODES.map((node) => overrides[node] ?? state(node, 'ok')));
		expect(
			stuck(all({ judge: state('judge', 'uncertain'), ocr: state('ocr', 'failed') })).map(
				(step) => step.node
			)
		).toEqual(['ocr']);
		expect(stuck(all({ judge: state('judge', 'uncertain') })).map((step) => step.node)).toEqual([
			'judge'
		]);
		expect(stuck(all({}))).toEqual([]);
	});
});

describe('countsOf', () => {
	it('counts how the steps of a run stand, and what it kept from an earlier run', () => {
		const log = [entry('receive', 1), entry('ocr', 2), entry('judge', 2, 'uncertain')];
		const steps = current(
			[
				state('receive', 'ok'),
				state('ocr', 'ok'),
				state('signal_llm', null, 'running'),
				state('judge', 'uncertain'),
				state('apply_rules', null, 'skipped'),
				state('file', null, 'waiting')
			],
			log,
			2
		);
		expect(countsOf(steps)).toEqual({
			done: 1,
			uncertain: 1,
			failed: 0,
			running: 1,
			waiting: 1,
			skipped: 1,
			carried: 1,
			carriedFrom: 1
		});
	});
});

describe('overruled steps', () => {
	it('tells a step a person confirmed in the inbox', () => {
		const log = [entry('judge', 1, 'uncertain'), confirmation('judge', 2, 'uncertain')];
		const steps = current(
			NODES.map((node) => state(node, 'ok')),
			log,
			2,
			'completed'
		);
		expect(judgeOf(steps)?.overruled).toBe('confirmed');
		expect(judgeOf(past(log, 2, 'completed'))?.overruled).toBe('confirmed');
	});

	it('tells a step the rules settled in its run, also once the run is past', () => {
		const log = [entry('judge', 1, 'uncertain'), entry('apply_rules', 1), entry('file', 1)];
		const live = current(
			NODES.map((node) => state(node, 'ok')),
			log,
			1,
			'completed'
		);
		expect(judgeOf(live)?.overruled).toBe('settled');
		const filed = judgeOf(past(log, 1, 'completed'));
		expect(filed?.state?.outcome).toBe('ok');
		expect(filed?.overruled).toBe('settled');
	});

	it('leaves a step as it ended where nothing overruled it', () => {
		const log = [entry('judge', 1, 'uncertain')];
		const stopped = judgeOf(past(log, 1, 'review'));
		expect(stopped?.state?.outcome).toBe('uncertain');
		expect(stopped?.overruled).toBeNull();
		const waiting = current([state('judge', 'uncertain')], log, 1, 'review');
		expect(judgeOf(waiting)?.overruled).toBeNull();
		expect(judgeOf(current([state('judge', 'ok')], [entry('judge', 1)]))?.overruled).toBeNull();
	});
});
