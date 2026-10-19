import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import type { GraphNode, Processing } from '#lib/pipeline.ts';
import { adviceText, visionAvailable, type Reading } from './vision.ts';

const GRAPH: GraphNode[] = [
	{ node: 'receive', requires: [] },
	{ node: 'ocr', requires: ['receive'] },
	{ node: 'pages', requires: ['receive'] },
	{ node: 'parse', requires: ['ocr'] },
	{ node: 'file', requires: ['parse', 'pages'] }
];
const VISION = { model: 'claude-sonnet', endpoint: 'chat.example' };

function processing(
	status: Processing['status'],
	failed: GraphNode['node'] | null = null
): Processing {
	return {
		status,
		run: 1,
		vision: false,
		nodes: GRAPH.map(({ node }) => ({
			node,
			status: 'done',
			outcome: node === failed ? 'failed' : 'ok',
			started_at: null,
			finished_at: null
		}))
	};
}

describe('visionAvailable', () => {
	it('needs a model, no processing under way and a way back to OCR', () => {
		expect(visionAvailable(VISION, GRAPH, processing('completed'))).toBe(true);
		expect(visionAvailable(null, GRAPH, processing('completed'))).toBe(false);
		expect(visionAvailable(VISION, GRAPH, processing('processing'))).toBe(false);
		// Reading again from OCR repeats a failed parse, but cannot skip failed page images.
		expect(visionAvailable(VISION, GRAPH, processing('failed', 'parse'))).toBe(true);
		expect(visionAvailable(VISION, GRAPH, processing('failed', 'pages'))).toBe(false);
		// The graph is not loaded yet.
		expect(visionAvailable(VISION, [], processing('completed'))).toBe(false);
	});
});

describe('adviceText', () => {
	const pages: Reading['pages'] = [
		{ page: 1, words: 120, unsure: 2, content: null, content_unsure: null, poor: false },
		{ page: 2, words: 50, unsure: 9, content: 45, content_unsure: 9, poor: true },
		{ page: 3, words: 40, unsure: 8, content: null, content_unsure: null, poor: true }
	];

	it('says why the model is advised', () => {
		expect(adviceText({ vision: false, pages: [], advice: 'no_text' })).toBe(
			m.vision_advice_no_text()
		);
		expect(adviceText({ vision: false, pages, advice: 'poor_page' })).toBe(
			m.vision_advice_poor_page({ pages: '2, 3' })
		);
	});

	it('says nothing without advice', () => {
		expect(adviceText(null)).toBeNull();
		expect(adviceText({ vision: true, pages, advice: null })).toBeNull();
	});
});
