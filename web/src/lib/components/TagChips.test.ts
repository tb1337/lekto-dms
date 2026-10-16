import { render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';
import type { Lookup, Tag } from '#lib/masterdata.svelte.ts';
import { SEPARATOR } from '#lib/tags.ts';
import TagChips from './TagChips.svelte';

function tag(id: string, path: string[], parent: string | null, scope: string, shown: boolean) {
	return {
		id,
		name: path[path.length - 1],
		path,
		parent_id: parent,
		scope,
		assignment: scope === 'document' ? 'auto' : 'manual',
		shown,
		created_at: '2026-10-16T12:00:00Z'
	} as Tag;
}

const lookup = {
	contacts: [{ id: 'c1', name: 'Nord', group_ids: ['g2'] }],
	documentTypes: [{ id: 'k1', name: 'Invoice', group_ids: ['g3'] }],
	tags: [
		tag('t1', ['Insurance'], null, 'document', true),
		tag('t2', ['Insurance', 'Health'], 't1', 'document', true),
		tag('t3', ['Paid'], null, 'document', false),
		tag('g1', ['Insurer'], null, 'contact', true),
		tag('g2', ['Insurer', 'Health insurer'], 'g1', 'contact', false),
		tag('g3', ['Bills'], null, 'document_type', false)
	],
	fields: [],
	spaces: [],
	users: []
} as unknown as Lookup;

describe('TagChips', () => {
	it('shows the shown tags and groups by their own names, the path as tooltip', () => {
		render(TagChips, {
			document: { tag_ids: ['t2', 't3'], contact_id: 'c1', document_type_id: 'k1' },
			lookup
		});
		expect(screen.getByText('Health').closest('[title]')?.getAttribute('title')).toBe(
			`Insurance${SEPARATOR}Health`
		);
		expect(screen.queryByText('Paid')).toBeNull(); // hidden
		// The contact's group is hidden, the one above it shown; the type's group is hidden.
		expect(screen.getByText('Insurer')).toBeTruthy();
		expect(screen.queryByText('Bills')).toBeNull();
	});
});
