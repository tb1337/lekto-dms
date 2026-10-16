import { fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { m } from '#lib/paraglide/messages.js';
import TagTreeList from './TagTreeList.svelte';

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

function tag(id: string, path: string[], parent: string | null, extra: object = {}) {
	return {
		id,
		name: path[path.length - 1],
		path,
		parent_id: parent,
		scope: 'document',
		assignment: 'auto',
		shown: true,
		document_count: 0,
		created_at: '2026-10-16T12:00:00Z',
		...extra
	};
}

beforeEach(() => {
	fetchMock.mockReset();
	fetchMock.mockImplementation(async (request) => {
		const url = new URL(request.url);
		expect(url.pathname).toBe('/api/v1/tags');
		expect(url.searchParams.get('scope')).toBe('document');
		return new Response(
			JSON.stringify([
				tag('t1', ['Insurance'], null, { document_count: 3 }),
				tag('t2', ['Insurance', 'Health'], 't1', { assignment: 'manual', shown: false }),
				tag('t3', ['Paid'], null)
			]),
			{ headers: { 'content-type': 'application/json' } }
		);
	});
	vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => vi.unstubAllGlobals());

describe('TagTreeList', () => {
	it('shows the tree with counts, and collapses a tag with tags below it', async () => {
		render(TagTreeList, { kind: 'tags' });
		expect(await screen.findByText('Health')).toBeTruthy();
		expect(screen.getByText(`${m.tag_assignment_manual()} · ${m.tag_hidden()}`)).toBeTruthy();
		const count = screen.getByRole('link', { name: m.master_documents({ count: '3' }) });
		expect(count.getAttribute('href')).toContain('/documents?tag=t1');
		const collapse = screen.getByRole('button', { name: m.tree_collapse({ name: 'Insurance' }) });
		expect(collapse.getAttribute('aria-expanded')).toBe('true');
		await fireEvent.click(collapse);
		expect(screen.queryByText('Health')).toBeNull();
		expect(screen.getByText('Paid')).toBeTruthy();
		await fireEvent.click(
			screen.getByRole('button', { name: m.tree_expand({ name: 'Insurance' }) })
		);
		expect(screen.getByText('Health')).toBeTruthy();
	});
});
