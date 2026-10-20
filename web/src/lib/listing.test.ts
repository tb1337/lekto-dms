import { afterEach, describe, expect, it } from 'vitest';
import {
	byMonth,
	monthOf,
	rememberSort,
	rememberLayout,
	rememberedLayout,
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

	it('remembers grid or list, grid at first', () => {
		expect(rememberedLayout()).toBe('grid');
		rememberLayout('list');
		expect(rememberedLayout()).toBe('list');
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
