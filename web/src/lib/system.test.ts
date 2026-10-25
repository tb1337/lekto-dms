import { describe, expect, it } from 'vitest';
import { systemTab } from './system.ts';

describe('the tab of the page "System"', () => {
	it('is the one the URL names, else the first', () => {
		expect(systemTab(new URLSearchParams('tab=jobs'))).toBe('jobs');
		expect(systemTab(new URLSearchParams('tab=search'))).toBe('search');
		expect(systemTab(new URLSearchParams(''))).toBe('classifier');
		expect(systemTab(new URLSearchParams('tab=nonsense'))).toBe('classifier');
	});
});
