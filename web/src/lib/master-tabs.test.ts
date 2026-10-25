import { describe, expect, it } from 'vitest';
import { masterTabOf } from './master-tabs.ts';

describe('the tab of the master data page', () => {
	it('is the one the URL names, else the first', () => {
		expect(masterTabOf(new URLSearchParams('tab=tags'))).toBe('tags');
		expect(masterTabOf(new URLSearchParams('tab=document-types'))).toBe('document-types');
		expect(masterTabOf(new URLSearchParams(''))).toBe('contacts');
		expect(masterTabOf(new URLSearchParams('tab=constructor'))).toBe('contacts');
	});
});
