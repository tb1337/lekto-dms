import { describe, expect, it } from 'vitest';
import {
	descendants,
	durationSeconds,
	levels,
	progress,
	reprocessable,
	type GraphNode,
	type Processing
} from './pipeline.ts';

const GRAPH: GraphNode[] = [
	{ node: 'receive', requires: [] },
	{ node: 'ocr', requires: ['receive'] },
	{ node: 'pages', requires: ['receive'] },
	{ node: 'parse', requires: ['ocr'] },
	{ node: 'classify', requires: ['parse'] },
	{ node: 'extract_fields', requires: ['classify'] },
	{ node: 'apply_rules', requires: ['extract_fields'] },
	{ node: 'file', requires: ['apply_rules', 'pages'] }
];

function processing(
	status: Processing['status'],
	outcomes: Partial<Record<GraphNode['node'], 'ok' | 'uncertain' | 'failed'>>
): Processing {
	return {
		status,
		run: 1,
		nodes: GRAPH.map(({ node }) => ({
			node,
			status: outcomes[node] ? 'done' : 'waiting',
			outcome: outcomes[node] ?? null,
			started_at: null,
			finished_at: null
		}))
	};
}

describe('descendants', () => {
	it('follows the edges to every node after the given one', () => {
		expect([...descendants(GRAPH, 'pages')]).toEqual(['file']);
		expect([...descendants(GRAPH, 'extract_fields')].sort()).toEqual(['apply_rules', 'file']);
		expect(descendants(GRAPH, 'file').size).toBe(0);
		expect(descendants(GRAPH, 'receive').size).toBe(7);
	});
});

describe('reprocessable', () => {
	it('offers every node but receiving for a finished document', () => {
		const green = processing('completed', {
			receive: 'ok',
			ocr: 'ok',
			pages: 'ok',
			parse: 'ok',
			classify: 'ok',
			extract_fields: 'ok',
			apply_rules: 'ok',
			file: 'ok'
		});
		expect(reprocessable(GRAPH, green)).toEqual([
			'ocr',
			'pages',
			'parse',
			'classify',
			'extract_fields',
			'apply_rules',
			'file'
		]);
	});

	it('never skips a failed node', () => {
		const red = processing('failed', { receive: 'ok', ocr: 'ok', pages: 'ok', parse: 'failed' });
		expect(reprocessable(GRAPH, red)).toEqual(['ocr', 'parse']);
		const pagesFailed = processing('failed', { receive: 'ok', ocr: 'ok', pages: 'failed' });
		expect(reprocessable(GRAPH, pagesFailed)).toEqual(['pages']);
	});

	it('does not file while results wait for confirmation', () => {
		const yellow = processing('review', {
			receive: 'ok',
			ocr: 'ok',
			pages: 'ok',
			parse: 'ok',
			classify: 'uncertain',
			extract_fields: 'ok',
			apply_rules: 'ok'
		});
		expect(reprocessable(GRAPH, yellow)).not.toContain('file');
		expect(reprocessable(GRAPH, yellow)).toContain('apply_rules');
	});
});

describe('levels', () => {
	it('puts nodes that run side by side into one row', () => {
		expect(levels(GRAPH)).toEqual([
			['receive'],
			['ocr', 'pages'],
			['parse'],
			['classify'],
			['extract_fields'],
			['apply_rules'],
			['file']
		]);
	});
});

describe('progress', () => {
	it('counts the done and skipped nodes and names the running ones', () => {
		const state = processing('processing', { receive: 'ok', ocr: 'ok' });
		state.nodes[2] = { ...state.nodes[2], status: 'skipped' };
		state.nodes[3] = { ...state.nodes[3], status: 'running', started_at: '2026-10-06T12:00:00Z' };
		expect(progress(state)).toEqual({ done: 3, total: 8, running: ['parse'] });
	});
});

describe('durationSeconds', () => {
	const now = new Date('2026-10-06T12:00:10Z');
	const waiting = { node: 'ocr', status: 'waiting', outcome: null } as const;

	it('is unknown before the node started', () => {
		expect(durationSeconds({ ...waiting, started_at: null, finished_at: null }, now)).toBeNull();
	});

	it('runs with the clock until the node finished', () => {
		const started_at = '2026-10-06T12:00:03Z';
		expect(durationSeconds({ ...waiting, started_at, finished_at: null }, now)).toBe(7);
		const finished_at = '2026-10-06T12:00:05.500Z';
		expect(durationSeconds({ ...waiting, started_at, finished_at }, now)).toBe(2.5);
	});
});
