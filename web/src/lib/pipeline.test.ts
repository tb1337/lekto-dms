import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	descendants,
	durationSeconds,
	forgetPipeline,
	hasText,
	levels,
	pipeline,
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
	{ node: 'judge', requires: ['parse'] },
	{ node: 'fields', requires: ['judge'] },
	{ node: 'apply_rules', requires: ['fields'] },
	{ node: 'file', requires: ['apply_rules', 'pages'] }
];

function processing(
	status: Processing['status'],
	outcomes: Partial<Record<GraphNode['node'], 'ok' | 'uncertain' | 'failed'>>
): Processing {
	return {
		status,
		run: 1,
		vision: false,
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
		expect([...descendants(GRAPH, 'fields')].sort()).toEqual(['apply_rules', 'file']);
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
			judge: 'ok',
			fields: 'ok',
			apply_rules: 'ok',
			file: 'ok'
		});
		expect(reprocessable(GRAPH, green)).toEqual([
			'ocr',
			'pages',
			'parse',
			'judge',
			'fields',
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
			judge: 'uncertain',
			fields: 'ok',
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
			['judge'],
			['fields'],
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

describe('hasText', () => {
	it('knows the text once the first run read it', () => {
		expect(hasText(processing('processing', { receive: 'ok' }))).toBe(false);
		expect(hasText(processing('failed', { receive: 'ok', ocr: 'failed' }))).toBe(false);
		expect(hasText(processing('failed', { receive: 'ok', ocr: 'ok', parse: 'failed' }))).toBe(
			false
		);
		expect(hasText(processing('processing', { receive: 'ok', ocr: 'ok', parse: 'ok' }))).toBe(true);
	});

	it('takes a later run for one with the text of a run before', () => {
		expect(hasText({ ...processing('processing', { receive: 'ok' }), run: 2 })).toBe(true);
	});
});

describe('the pipeline of the installation', () => {
	afterEach(() => {
		vi.unstubAllGlobals();
		forgetPipeline();
	});

	it('is asked for once, and again only after a failure', async () => {
		let fail = true;
		const fetch = vi.fn(async () =>
			fail
				? new Response(null, { status: 503 })
				: new Response(JSON.stringify({ nodes: GRAPH, vision: null }), {
						headers: { 'content-type': 'application/json' }
					})
		);
		vi.stubGlobal('fetch', fetch);
		await expect(pipeline()).rejects.toBeTruthy();
		fail = false;
		const [first, second] = await Promise.all([pipeline(), pipeline()]);
		expect(first).toBe(second);
		expect((await pipeline()).nodes).toEqual(GRAPH);
		expect(fetch).toHaveBeenCalledTimes(2);
	});
});
