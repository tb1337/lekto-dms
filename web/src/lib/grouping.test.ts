import { describe, expect, it } from 'vitest';
import type { Lookup } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';
import { groupDocuments, type Grouped } from './grouping.ts';

const TODAY = new Date(2026, 9, 20);

type Doc = Grouped & { id: string };

function doc(id: string, parts: Partial<Doc> = {}): Doc {
	return { id, created_at: '2026-10-01T10:00:00Z', document_date: null, ...parts };
}

const lookup = {
	documentTypes: [
		{ id: 't1', name: 'Rechnung' },
		{ id: 't2', name: 'Brief' }
	],
	contacts: [{ id: 'c1', name: 'Stadtwerke' }]
} as unknown as Lookup;

function grouped(
	items: Doc[],
	grouping: Parameters<typeof groupDocuments>[1],
	sort = '-document_date'
) {
	return groupDocuments(items, grouping, (item) => item, {
		sort: sort as never,
		dueField: 'due',
		today: TODAY,
		lookup
	}).map((group) => [group.label, group.tone, group.items.map((item) => item.id)]);
}

describe('grouping the documents', () => {
	it('without a lens by month while sorted by a date, not while sorted by title', () => {
		const items = [
			doc('a', { document_date: '2026-10-02' }),
			doc('b', { document_date: '2026-09-30' })
		];
		expect(grouped(items, 'sort').map(([label]) => label)).toHaveLength(2);
		expect(grouped(items, 'sort', 'title')).toEqual([[null, null, ['a', 'b']]]);
	});

	it('by how soon the deadline is due: overdue, soon, later, none', () => {
		const items = [
			doc('later', { fields: { due: '2026-12-01' } }),
			doc('none'),
			doc('soon', { fields: { due: '2026-10-22' } }),
			doc('overdue', { fields: { due: '2026-10-01' } })
		];
		expect(grouped(items, 'due')).toEqual([
			[m.lens_group_overdue(), 'overdue', ['overdue']],
			[m.lens_group_soon(), 'soon', ['soon']],
			[m.lens_group_later(), null, ['later']],
			[m.lens_group_no_due(), null, ['none']]
		]);
	});

	it('by type or contact by name, those without one last, in the order of the list', () => {
		const items = [
			doc('x', { document_type_id: 't1' }),
			doc('y'),
			doc('z', { document_type_id: 't2', contact_id: 'c1' }),
			doc('w', { document_type_id: 't1' })
		];
		expect(grouped(items, 'document_type')).toEqual([
			['Brief', null, ['z']],
			['Rechnung', null, ['x', 'w']],
			[m.lens_group_no_type(), null, ['y']]
		]);
		expect(grouped(items, 'contact').map(([label]) => label)).toEqual([
			'Stadtwerke',
			m.lens_group_no_contact()
		]);
	});

	it('in a lens by the month of the document date whatever the sort, newest first', () => {
		const items = [
			doc('sep', { document_date: '2026-09-30' }),
			doc('none'),
			doc('oct', { document_date: '2026-10-02' }),
			doc('sep2', { document_date: '2026-09-01' })
		];
		const groups = grouped(items, 'month', 'title');
		expect(groups.map(([, , ids]) => ids)).toEqual([['oct'], ['sep', 'sep2'], ['none']]);
		expect(groups.at(-1)?.[0]).toBe(m.documents_no_date());
	});
});
