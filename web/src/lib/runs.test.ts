import { describe, expect, it } from 'vitest';
import type { components } from '#lib/api/schema.ts';
import type { GraphNode, Processing } from '#lib/pipeline.ts';
import {
	glance,
	glanceSeconds,
	nodeRun,
	pastStatus,
	runNumbers,
	runSpan,
	runTokens,
	startedAgain,
	stateOf
} from './runs.ts';

type LogEntry = components['schemas']['LogEntry'];

const GRAPH: GraphNode[] = [
	{ node: 'receive', requires: [] },
	{ node: 'ocr', requires: ['receive'] },
	{ node: 'parse', requires: ['ocr'] },
	{ node: 'judge', requires: ['parse'] },
	{ node: 'fields', requires: ['judge'] },
	{ node: 'apply_rules', requires: ['fields'] },
	{ node: 'file', requires: ['apply_rules'] }
];

function entry(
	node: LogEntry['node'],
	run: number,
	outcome: LogEntry['outcome'] = 'ok',
	started_at = '2026-10-14T08:49:01Z',
	extra: Partial<LogEntry> = {}
): LogEntry {
	return {
		node,
		run,
		outcome,
		reason: null,
		confidence: null,
		model_version: null,
		input: {},
		output: {},
		pipeline_version: 'test',
		started_at,
		duration_ms: 1000,
		...extra
	};
}

// Run 1 ends for review at the verdict; run 2 starts again at the verdict and ends for review
// at the fields; the owner confirms in run 2, and it files.
const LOG: LogEntry[] = [
	entry('receive', 1),
	entry('ocr', 1, 'uncertain'),
	entry('parse', 1, 'ok', '2026-10-14T08:49:05Z'),
	entry('judge', 1, 'uncertain', '2026-10-14T08:50:12Z'),
	entry('judge', 2, 'ok', '2026-10-14T08:51:54Z'),
	entry('fields', 2, 'uncertain', '2026-10-14T08:51:55Z'),
	entry('judge', 2, 'ok', '2026-10-14T09:30:00Z', { model_version: 'person' }),
	entry('apply_rules', 2, 'ok', '2026-10-14T09:30:01Z'),
	entry('file', 2, 'ok', '2026-10-14T09:30:02Z')
];

describe('runNumbers', () => {
	it('lists the runs of the log and the current one, the latest first', () => {
		expect(runNumbers(LOG, 2)).toEqual([2, 1]);
		expect(runNumbers(LOG, 3)).toEqual([3, 2, 1]);
		expect(runNumbers([], 1)).toEqual([1]);
	});
});

describe('startedAgain', () => {
	it('takes the nodes that ran and every node after them', () => {
		expect([...startedAgain(LOG, GRAPH, 2)].sort()).toEqual(
			['apply_rules', 'fields', 'file', 'judge'].sort()
		);
		// Run 1 started everything; filing waited for the review.
		expect(startedAgain(LOG, GRAPH, 1).has('file')).toBe(true);
	});
});

describe('nodeRun', () => {
	it('gives the entries of the run, in the order they were written', () => {
		const judged = nodeRun(LOG, 'judge', 2, true);
		expect(judged.from).toBeNull();
		expect(judged.entries.map((item) => item.model_version)).toEqual([null, 'person']);
	});

	it('keeps what a node not started again did in the latest earlier run', () => {
		const ocr = nodeRun(LOG, 'ocr', 2, false);
		expect(ocr.from).toBe(1);
		expect(ocr.entries).toEqual([LOG[1]]);
		expect(nodeRun(LOG, 'ocr', 3, false).from).toBe(1);
	});

	it('gives nothing for a node started again that did not run', () => {
		expect(nodeRun(LOG, 'file', 1, true)).toEqual({ entries: [], from: null });
		expect(nodeRun(LOG, 'pages', 2, false)).toEqual({ entries: [], from: null });
	});
});

describe('stateOf', () => {
	it('ends with the last entry', () => {
		expect(stateOf('judge', nodeRun(LOG, 'judge', 2, true).entries)).toEqual({
			node: 'judge',
			status: 'done',
			outcome: 'ok',
			started_at: '2026-10-14T09:30:00Z',
			finished_at: '2026-10-14T09:30:01.000Z'
		});
		expect(stateOf('file', [])).toBeNull();
	});
});

describe('pastStatus', () => {
	it('is done once the run filed, also after a confirmation', () => {
		expect(pastStatus(LOG, GRAPH, 2)).toBe('completed');
	});

	it('is for review or failed by the results the run worked with', () => {
		expect(pastStatus(LOG, GRAPH, 1)).toBe('review');
		const failed = [...LOG.slice(0, 3), entry('judge', 1, 'failed')];
		expect(pastStatus(failed, GRAPH, 1)).toBe('failed');
		// The uncertain OCR of run 1 still counts in a run that did not start it again.
		const kept = [...LOG.slice(0, 4), entry('judge', 2), entry('fields', 2)];
		expect(pastStatus(kept, GRAPH, 2)).toBe('review');
	});
});

describe('runSpan', () => {
	it('runs from the first entry to the end of the last', () => {
		expect(runSpan(LOG, 1)).toEqual({
			started: '2026-10-14T08:49:01.000Z',
			finished: '2026-10-14T08:50:13.000Z'
		});
		expect(runSpan(LOG, 3)).toBeNull();
	});
});

describe('runTokens', () => {
	it('adds up the tokens of the run', () => {
		const tokens = { tokens: [{ prompt: 2000, completion: 200 }] };
		const log = [
			entry('judge', 1, 'ok', undefined, { output: tokens }),
			entry('fields', 2, 'ok', undefined, { output: tokens }),
			entry('fields', 2, 'ok', undefined, { output: tokens })
		];
		expect(runTokens(log, 2)).toEqual({ input: 4000, output: 400 });
		expect(runTokens(LOG, 1)).toBeNull();
	});
});

describe('glance', () => {
	const processing = (status: Processing['status'], run: number): Processing => ({
		status,
		run,
		vision: false,
		nodes: [
			{
				node: 'receive',
				status: 'done',
				outcome: 'ok',
				started_at: '2026-10-14T08:49:01Z',
				finished_at: '2026-10-14T08:49:02Z'
			},
			{
				node: 'ocr',
				status: status === 'processing' ? 'running' : 'done',
				outcome: status === 'processing' ? null : 'ok',
				started_at: '2026-10-14T08:49:02Z',
				finished_at: status === 'processing' ? null : '2026-10-14T08:49:30Z'
			}
		]
	});

	it('reads a past run from the log and the current one from its state', () => {
		const past = glance(LOG, GRAPH, processing('review', 2), 1);
		expect(past).toEqual({
			status: 'review',
			started: '2026-10-14T08:49:01.000Z',
			finished: '2026-10-14T08:50:13.000Z'
		});
		expect(glanceSeconds(past)).toBe(72);
		expect(glance(LOG, GRAPH, processing('completed', 2), 2).status).toBe('completed');
	});

	it('takes the states of the nodes without the log, and has no end while running', () => {
		expect(glance(null, GRAPH, processing('completed', 1), 1)).toEqual({
			status: 'completed',
			started: '2026-10-14T08:49:01Z',
			finished: '2026-10-14T08:49:30Z'
		});
		const running = glance(null, GRAPH, processing('processing', 1), 1);
		expect(running.finished).toBeNull();
		expect(glanceSeconds(running)).toBeNull();
	});
});
