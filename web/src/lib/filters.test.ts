import { describe, expect, it } from 'vitest';
import {
	apiQuery,
	isFiltered,
	monthPeriod,
	NO_FILTERS,
	parseFilters,
	periodOf,
	writeFilters,
	yearPeriod
} from './filters.ts';

describe('filters in the URL', () => {
	it('reads and writes all of them', () => {
		const params = new URLSearchParams(
			'contact=c1&contact=c2&type=t1&tag=a&tag=b&contact_group=g1&type_group=g2&type_group=g3' +
				'&space=d1&lane=red&lane=bogus&field=f1&topic=p1&topic=p2&date_from=2026-09-01' +
				'&date_to=2026-09-30&q=x&fact=invoice_number:4711:refers&fact=::own'
		);
		const filters = parseFilters(params);
		expect(filters).toEqual({
			contacts: ['c1', 'c2'],
			types: ['t1'],
			tags: ['a', 'b'],
			contactGroups: ['g1'],
			typeGroups: ['g2', 'g3'],
			topics: ['p1', 'p2'],
			spaces: ['d1'],
			field: 'f1',
			dateFrom: '2026-09-01',
			dateTo: '2026-09-30',
			facts: ['invoice_number:4711:refers', '::own']
		});
		// The archive has no lanes; an older link's lane narrows nothing.
		expect(apiQuery(filters)).not.toHaveProperty('lane');
		const out = writeFilters(new URLSearchParams('q=x&tag=old&contact_group=old'), filters);
		expect(out.getAll('contact')).toEqual(['c1', 'c2']);
		expect(out.getAll('tag')).toEqual(['a', 'b']);
		expect(out.getAll('contact_group')).toEqual(['g1']);
		expect(out.getAll('type_group')).toEqual(['g2', 'g3']);
		expect(out.get('date_from')).toBe('2026-09-01');
		// Several contacts, types, spaces or topics: one of them.
		expect(apiQuery(filters).contact_id).toEqual(['c1', 'c2']);
		expect(apiQuery(filters).document_type_id).toEqual(['t1']);
		expect(apiQuery(filters).space_id).toEqual(['d1']);
		expect(apiQuery(filters).contact_group_id).toEqual(['g1']);
		expect(apiQuery(filters).document_type_group_id).toEqual(['g2', 'g3']);
		expect(out.getAll('topic')).toEqual(['p1', 'p2']);
		expect(apiQuery(filters).topic_id).toEqual(['p1', 'p2']);
		expect(apiQuery(filters).document_date_from).toBe('2026-09-01');
		expect(apiQuery(filters).document_date_to).toBe('2026-09-30');
		expect(out.get('q')).toBe('x');
		// Facts: all of them.
		expect(out.getAll('fact')).toEqual(['invoice_number:4711:refers', '::own']);
		expect(apiQuery(filters).fact).toEqual(['invoice_number:4711:refers', '::own']);
		// Whom the list covers is a setting, not part of the link.
		expect(out.has('all')).toBe(false);
		expect(apiQuery(filters, true).all_users).toBe(true);
		expect(apiQuery(filters).all_users).toBeUndefined();
	});

	it('leaves out what is not set, and a day that is none', () => {
		expect(writeFilters(new URLSearchParams(), NO_FILTERS).toString()).toBe('');
		expect(apiQuery(NO_FILTERS)).toEqual({
			contact_id: undefined,
			document_type_id: undefined,
			tag_id: undefined,
			contact_group_id: undefined,
			document_type_group_id: undefined,
			topic_id: undefined,
			space_id: undefined,
			field_id: undefined,
			document_date_from: undefined,
			document_date_to: undefined,
			fact: undefined,
			all_users: undefined
		});
		expect(parseFilters(new URLSearchParams('date_from=gestern')).dateFrom).toBeNull();
		expect(parseFilters(new URLSearchParams('contact_group=&contact=c1&field='))).toEqual({
			...NO_FILTERS,
			contacts: ['c1']
		});
		expect(isFiltered(NO_FILTERS)).toBe(false);
		expect(isFiltered({ ...NO_FILTERS, tags: ['a'] })).toBe(true);
		expect(isFiltered({ ...NO_FILTERS, contacts: ['c1'] })).toBe(true);
		expect(isFiltered({ ...NO_FILTERS, field: 'f1' })).toBe(true);
		expect(isFiltered({ ...NO_FILTERS, typeGroups: ['g1'] })).toBe(true);
		expect(isFiltered({ ...NO_FILTERS, topics: ['p1'] })).toBe(true);
		expect(isFiltered({ ...NO_FILTERS, dateTo: '2026-01-01' })).toBe(true);
	});
});

describe('the period of the document date', () => {
	it('is a whole year, a whole month or a span', () => {
		expect(yearPeriod(2026)).toEqual({ dateFrom: '2026-01-01', dateTo: '2026-12-31' });
		expect(monthPeriod('2026-02')).toEqual({ dateFrom: '2026-02-01', dateTo: '2026-02-28' });
		expect(monthPeriod('2024-02').dateTo).toBe('2024-02-29');
		expect(periodOf(yearPeriod(2026))).toEqual({ kind: 'year', year: 2026 });
		expect(periodOf(monthPeriod('2026-09'))).toEqual({ kind: 'month', month: '2026-09' });
		expect(periodOf({ dateFrom: '2026-09-02', dateTo: null })).toEqual({
			kind: 'span',
			from: '2026-09-02',
			to: null
		});
		expect(periodOf({ dateFrom: null, dateTo: null })).toBeNull();
	});
});
