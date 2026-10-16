import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { Processing } from '#lib/pipeline.ts';
import { m } from '#lib/paraglide/messages.js';
import ProcessingProgress from './ProcessingProgress.svelte';

const state = (node: string, status: string, outcome: string | null = null) => ({
	node,
	status,
	outcome,
	started_at: null,
	finished_at: null
});

const PROCESSING = {
	status: 'processing',
	run: 1,
	vision: false,
	nodes: [
		state('receive', 'done', 'ok'),
		state('ocr', 'running'),
		state('pages', 'done', 'ok'),
		state('parse', 'waiting'),
		state('file', 'skipped')
	]
} as unknown as Processing;

describe('ProcessingProgress', () => {
	it('shows a segment per node, what runs, and how far it is', () => {
		render(ProcessingProgress, { processing: PROCESSING, href: '/ui/documents/d?tab=log' });
		const bar = screen.getByRole('progressbar', { name: m.processing_progress() });
		expect([bar.getAttribute('aria-valuenow'), bar.getAttribute('aria-valuemax')]).toEqual([
			'3',
			'5'
		]);
		expect(bar.children).toHaveLength(5);
		expect(bar.children[1].className).toContain('animate-pulse');
		expect(bar.children[1].getAttribute('title')).toContain(m.node_status_running());
		expect(screen.getByRole('status').textContent).toContain('3');
		expect(screen.getByRole('link').getAttribute('href')).toBe('/ui/documents/d?tab=log');
	});

	it('is a thin bar alone where it is small', () => {
		render(ProcessingProgress, { processing: PROCESSING, compact: true });
		expect(screen.getByRole('progressbar')).toBeTruthy();
		expect(screen.queryByRole('status')).toBeNull();
		expect(screen.queryByRole('link')).toBeNull();
	});
});
