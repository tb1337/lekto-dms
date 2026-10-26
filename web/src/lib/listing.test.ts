import { afterEach, describe, expect, it } from 'vitest';
import { NO_FILTERS } from './filters.ts';
import {
	byMonth,
	filtersCollapsed,
	monthOf,
	rememberFilters,
	rememberFiltersCollapsed,
	rememberSort,
	rememberLayout,
	rememberedFilters,
	rememberedLayout,
	sortFieldOf,
	sortOf
} from './listing.ts';

afterEach(() => localStorage.clear());

describe('the sort of the document view', () => {
	it('defaults to relevance for a search and to the newest document date for a list', () => {
		expect(sortOf(new URLSearchParams(), true)).toBe('relevance');
		expect(sortOf(new URLSearchParams(), false)).toBe('-document_date');
	});

	it('takes the URL first, then what this browser chose, each for a list or a search', () => {
		rememberSort('title', false);
		rememberSort('-created_at', true);
		expect(sortOf(new URLSearchParams(), false)).toBe('title');
		expect(sortOf(new URLSearchParams(), true)).toBe('-created_at');
		expect(sortOf(new URLSearchParams('sort=document_date'), false)).toBe('document_date');
		// Relevance only where something is searched; nonsense counts as missing.
		expect(sortOf(new URLSearchParams('sort=relevance'), false)).toBe('title');
		expect(sortOf(new URLSearchParams('sort=size'), true)).toBe('-created_at');
	});

	it('sorts a list by a field named in the URL, never a search, and does not remember it', () => {
		const byDue = new URLSearchParams('sort=field&sort_field=f1');
		expect(sortOf(byDue, false)).toBe('field');
		expect(sortFieldOf(byDue, false)).toBe('f1');
		expect(sortOf(new URLSearchParams('sort=-field&sort_field=f1'), false)).toBe('-field');
		// Without the field, or while searching, it counts as missing.
		expect(sortOf(new URLSearchParams('sort=field'), false)).toBe('-document_date');
		expect(sortOf(byDue, true)).toBe('relevance');
		expect(sortFieldOf(byDue, true)).toBeNull();
		expect(sortFieldOf(new URLSearchParams('sort=title&sort_field=f1'), false)).toBeNull();
		rememberSort('field', false);
		expect(sortOf(new URLSearchParams(), false)).toBe('-document_date');
	});

	it('remembers grid or list, grid at first', () => {
		expect(rememberedLayout()).toBe('grid');
		rememberLayout('list');
		expect(rememberedLayout()).toBe('list');
	});
});

describe('the filters the document view remembers', () => {
	it('keeps the filters as set, and forgets them once none is left', () => {
		expect(rememberedFilters()).toBeNull();
		rememberFilters({ ...NO_FILTERS, contacts: ['c1', 'c2'], dateFrom: '2026-01-01' });
		expect(rememberedFilters()).toEqual({
			...NO_FILTERS,
			contacts: ['c1', 'c2'],
			dateFrom: '2026-01-01'
		});
		rememberFilters(NO_FILTERS);
		expect(rememberedFilters()).toBeNull();
		expect(localStorage.getItem('lekto.documents.filters')).toBeNull();
	});

	it('counts what was stored but narrows nothing as none', () => {
		localStorage.setItem('lekto.documents.filters', 'contact=&date_from=yesterday');
		expect(rememberedFilters()).toBeNull();
	});

	it('remembers the panel collapsed, open at first', () => {
		expect(filtersCollapsed()).toBe(false);
		rememberFiltersCollapsed(true);
		expect(filtersCollapsed()).toBe(true);
		rememberFiltersCollapsed(false);
		expect(filtersCollapsed()).toBe(false);
		expect(localStorage.getItem('lekto.documents.filters-collapsed')).toBeNull();
	});

	it('works without storage: nothing remembered, nothing thrown', () => {
		const storage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')!;
		Object.defineProperty(globalThis, 'localStorage', {
			configurable: true,
			get() {
				throw new Error('blocked');
			}
		});
		try {
			expect(() => rememberFilters({ ...NO_FILTERS, contacts: ['c1'] })).not.toThrow();
			expect(rememberedFilters()).toBeNull();
			expect(() => rememberFiltersCollapsed(true)).not.toThrow();
			expect(filtersCollapsed()).toBe(false);
		} finally {
			Object.defineProperty(globalThis, 'localStorage', storage);
		}
	});
});

describe('the months of the document view', () => {
	const doc = (document_date: string | null, created_at = '2026-10-18T08:00:00') => ({
		document_date,
		created_at
	});

	it('groups a sort by date by month, and nothing else', () => {
		expect(monthOf('-document_date', doc('2026-09-30'))).toBe('2026-09');
		expect(monthOf('document_date', doc(null))).toBe('');
		expect(monthOf('-created_at', doc('2026-09-30', '2026-10-01T09:00:00'))).toBe('2026-10');
		expect(monthOf('title', doc('2026-09-30'))).toBeNull();
		expect(monthOf('relevance', doc('2026-09-30'))).toBeNull();
	});

	it('keeps the order, a group for each run of one month', () => {
		const items = [doc('2026-10-14'), doc('2026-10-01'), doc('2026-09-30'), doc(null)];
		const groups = byMonth(items, '-document_date', (item) => item);
		expect(groups.map((group) => [group.month, group.start, group.items.length])).toEqual([
			['2026-10', 0, 2],
			['2026-09', 2, 1],
			['', 3, 1]
		]);
		expect(byMonth(items, 'title', (item) => item)).toEqual([{ month: null, start: 0, items }]);
	});
});
