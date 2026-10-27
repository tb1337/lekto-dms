import { describe, expect, it } from 'vitest';
import { GAP, pageCount, pageSlots } from './pagination.ts';

describe('the page slots', () => {
	it('show every page while they are few', () => {
		expect(pageSlots(1, 1)).toEqual([1]);
		expect(pageSlots(1, 0)).toEqual([1]);
		expect(pageSlots(2, 4)).toEqual([1, 2, 3, 4]);
		expect(pageSlots(1, 5)).toEqual([1, 2, GAP, 5]);
		expect(pageSlots(2, 5)).toEqual([1, 2, 3, 4, 5]); // 4 fills the gap of one page
		expect(pageSlots(3, 5)).toEqual([1, 2, 3, 4, 5]);
	});

	it('leave out the pages far from the current one', () => {
		expect(pageSlots(1, 26)).toEqual([1, 2, GAP, 26]);
		expect(pageSlots(10, 26)).toEqual([1, GAP, 9, 10, 11, GAP, 26]);
		expect(pageSlots(26, 26)).toEqual([1, GAP, 25, 26]);
		expect(pageSlots(3, 26)).toEqual([1, 2, 3, 4, GAP, 26]);
	});

	it('count the pages', () => {
		expect(pageCount(0, 50)).toBe(1);
		expect(pageCount(50, 50)).toBe(1);
		expect(pageCount(51, 50)).toBe(2);
	});
});
