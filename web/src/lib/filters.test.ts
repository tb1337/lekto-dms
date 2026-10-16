import { describe, expect, it } from 'vitest';
import { apiQuery, isFiltered, NO_FILTERS, parseFilters, writeFilters } from './filters.ts';

describe('filters in the URL', () => {
	it('reads and writes all of them', () => {
		const params = new URLSearchParams(
			'contact=c1&type=t1&tag=a&tag=b&space=d1&lane=red&lane=bogus&field=f1&q=x'
		);
		const filters = parseFilters(params);
		expect(filters).toEqual({
			contact: 'c1',
			type: 't1',
			tags: ['a', 'b'],
			space: 'd1',
			lanes: ['red'],
			field: 'f1'
		});
		const out = writeFilters(new URLSearchParams('q=x&tag=old'), filters);
		expect(out.getAll('tag')).toEqual(['a', 'b']);
		expect(out.get('q')).toBe('x');
		expect(out.getAll('lane')).toEqual(['red']);
		// Whom the list covers is a setting, not part of the link.
		expect(out.has('all')).toBe(false);
		expect(apiQuery(filters, true).all_users).toBe(true);
		expect(apiQuery(filters).all_users).toBeUndefined();
	});

	it('leaves out what is not set', () => {
		expect(writeFilters(new URLSearchParams(), NO_FILTERS).toString()).toBe('');
		expect(apiQuery(NO_FILTERS)).toEqual({
			contact_id: undefined,
			document_type_id: undefined,
			tag_id: undefined,
			space_id: undefined,
			lane: undefined,
			field_id: undefined,
			all_users: undefined
		});
		expect(isFiltered(NO_FILTERS)).toBe(false);
		expect(isFiltered({ ...NO_FILTERS, tags: ['a'] })).toBe(true);
		expect(isFiltered({ ...NO_FILTERS, field: 'f1' })).toBe(true);
	});
});
