import { describe, expect, it } from 'vitest';
import { monthLabel, systemTab } from './system.ts';

describe('the tab of the page "System"', () => {
	it('is the one the URL names, else the first', () => {
		expect(systemTab(new URLSearchParams('tab=jobs'))).toBe('jobs');
		expect(systemTab(new URLSearchParams('tab=search'))).toBe('search');
		expect(systemTab(new URLSearchParams(''))).toBe('automation');
		expect(systemTab(new URLSearchParams('tab=classifier'))).toBe('classifier');
		expect(systemTab(new URLSearchParams('tab=nonsense'))).toBe('automation');
	});
});

describe('the label of a month on the history', () => {
	it('names the month, with the year across years', () => {
		expect(monthLabel('2026-10-01', false)).toMatch(/^(Oct|Okt)/);
		expect(monthLabel('2026-10-01', false)).not.toMatch(/26/);
		expect(monthLabel('2025-10-01', true)).toMatch(/^(Oct|Okt)\.? ?25$/);
	});
});
