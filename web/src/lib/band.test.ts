import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { GraphNode, Node, NodeState } from '#lib/pipeline.ts';
import { bandOf, MIN_PHASE, shares } from './band.ts';
import { stepsOf } from './steps.ts';

type LogEntry = components['schemas']['LogEntry'];

const graph: GraphNode[] = [
	{ node: 'receive', requires: [] },
	{ node: 'ocr', requires: ['receive'] },
	{ node: 'pages', requires: ['receive'] },
	{ node: 'parse', requires: ['ocr'] },
	{ node: 'signal_llm', requires: ['parse'] },
	{ node: 'signal_classifier', requires: ['parse'] },
	{ node: 'judge', requires: ['signal_llm', 'signal_classifier'] },
	{ node: 'fields', requires: ['judge'] },
	{ node: 'apply_rules', requires: ['fields'] },
	{ node: 'file', requires: ['apply_rules'] }
];

/** A node that ran from `start` for `seconds` (seconds after 09:00:00). */
function ran(node: Node, start: number, seconds: number, outcome: NodeState['outcome'] = 'ok') {
	const at = (offset: number) => new Date(Date.UTC(2026, 9, 23, 9, 0, 0) + offset * 1000);
	return {
		node,
		status: 'done' as const,
		outcome,
		started_at: at(start).toISOString(),
		finished_at: at(start + seconds).toISOString()
	};
}

function entry(node: Node, run: number): LogEntry {
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
		duration_ms: 100
	};
}

function stepsFrom(states: NodeState[], log: LogEntry[] = [], run = 1) {
	return stepsOf(
		graph.map((entry) => entry.node),
		log,
		new Map(states.map((state) => [state.node, state])),
		{ number: run, current: true, again: new Set(), status: 'review' }
	);
}

describe('shares', () => {
	it('splits the bar by time, keeping a minimum for a short phase', () => {
		const parts = shares([4, 22, 11, 0.6]);
		expect(parts.reduce((sum, value) => sum + value, 0)).toBeCloseTo(1);
		expect(parts[3]).toBeCloseTo(MIN_PHASE);
		expect(parts[1]).toBeGreaterThan(parts[2]);
		expect(parts[2]).toBeGreaterThan(parts[0]);
	});

	it('gives equal parts without any time', () => {
		expect(shares([0, 0])).toEqual([0.5, 0.5]);
		expect(shares([])).toEqual([]);
	});
});

describe('bandOf', () => {
	it('lays steps that ran side by side on top of each other, the longest first', () => {
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
			{ node: 'file', status: 'waiting', outcome: null, started_at: null, finished_at: null }
		]);
		const band = bandOf(steps, graph, new Date());
		expect(band.map((phase) => phase.phase)).toEqual(['read', 'recognise', 'decide', 'file']);
		const read = band[0];
		// Receiving, then OCR beside the page images, then the parsing.
		expect(read.groups.map((group) => group.steps.map((step) => step.node))).toEqual([
			['receive'],
			['ocr', 'pages'],
			['parse']
		]);
		expect(read.groups[1].steps[1].share).toBeCloseTo(0.3 / 4);
		const recognise = band[1].groups[0];
		expect(recognise.steps.map((step) => step.node)).toEqual(['signal_llm', 'signal_classifier']);
		expect(recognise.weight).toBe(22);
		expect(band[2].groups[0].steps[0].tone).toBe('yellow');
		// The waiting filing stands for a short time of its own.
		const filing = band[3].groups[1].steps[0];
		expect(filing).toMatchObject({ node: 'file', tone: 'waiting', seconds: null });
		expect(band.reduce((sum, phase) => sum + phase.width, 0)).toBeCloseTo(1);
	});

	it('marks a phase the run kept whole from an earlier run', () => {
		// Run 2 started at the verdict: reading and recognising are run 1's.
		const log = [entry('receive', 1), entry('ocr', 1), entry('signal_llm', 1)];
		const steps = stepsFrom(
			[ran('receive', 0, 0.1), ran('ocr', 0.1, 4), ran('signal_llm', 5, 20), ran('judge', 60, 3)],
			log,
			2
		);
		const band = bandOf(steps, graph, new Date());
		expect(band.map((phase) => [phase.phase, phase.carried])).toEqual([
			['read', true],
			['recognise', true],
			['decide', false]
		]);
		expect(band[0].groups).toEqual([]);
	});
});
