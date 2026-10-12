import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import type { GraphNode, Processing } from '#lib/pipeline.ts';
import ProcessingGraph from './ProcessingGraph.svelte';

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

const PROCESSING: Processing = {
	status: 'processing',
	run: 1,
	nodes: [
		{
			node: 'receive',
			status: 'done',
			outcome: 'ok',
			started_at: '2026-10-06T12:00:00Z',
			finished_at: '2026-10-06T12:00:00.200Z'
		},
		{
			node: 'ocr',
			status: 'running',
			outcome: null,
			started_at: '2026-10-06T12:00:01Z',
			finished_at: null
		},
		{ node: 'pages', status: 'skipped', outcome: null, started_at: null, finished_at: null },
		...(['parse', 'classify', 'extract_fields', 'apply_rules', 'file'] as const).map((node) => ({
			node,
			status: 'waiting' as const,
			outcome: null,
			started_at: null,
			finished_at: null
		}))
	]
};

describe('ProcessingGraph', () => {
	it('shows every node with its state in rows by level', () => {
		render(ProcessingGraph, { processing: PROCESSING, graph: GRAPH });
		const rows = screen.getAllByRole('listitem');
		expect(rows).toHaveLength(7);
		expect(rows[1].querySelectorAll('[data-node]')).toHaveLength(2); // ocr and pages
		const ocr = screen.getByText(m.node_ocr()).closest('[data-node]') as HTMLElement;
		expect(ocr.dataset.status).toBe('running');
		expect(ocr.textContent).toContain(m.node_status_running());
		const receive = screen.getByText(m.node_receive()).closest('[data-node]') as HTMLElement;
		expect(receive.dataset.outcome).toBe('ok');
		expect(receive.textContent).toContain(m.outcome_ok());
		expect(receive.textContent).toContain('0.2');
		const pages = screen.getByText(m.node_pages()).closest('[data-node]') as HTMLElement;
		expect(pages.dataset.status).toBe('skipped');
	});

	it('falls back to one node per row without the graph', () => {
		render(ProcessingGraph, { processing: PROCESSING, graph: [] });
		expect(screen.getAllByRole('listitem')).toHaveLength(8);
	});
});
