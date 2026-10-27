import { afterEach, describe, expect, it } from 'vitest';
import { DEFAULT_PAGE_SIZES, rememberedPageSize, rememberPageSize } from './page-size.ts';

afterEach(() => localStorage.clear());

describe('the page size of a table', () => {
	it('is 25 for the jobs until one is chosen, then the one chosen', () => {
		expect(rememberedPageSize('jobs')).toBe(25);
		rememberPageSize('jobs', 100);
		expect(rememberedPageSize('jobs')).toBe(100);
		expect(localStorage.getItem('lekto.page-size.jobs')).toBe('100');
	});

	it('forgets the default and ignores a size the table does not offer', () => {
		rememberPageSize('jobs', 100);
		rememberPageSize('jobs', DEFAULT_PAGE_SIZES.jobs);
		expect(localStorage.getItem('lekto.page-size.jobs')).toBeNull();
		localStorage.setItem('lekto.page-size.jobs', '1000');
		expect(rememberedPageSize('jobs')).toBe(DEFAULT_PAGE_SIZES.jobs);
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
			expect(() => rememberPageSize('jobs', 100)).not.toThrow();
			expect(rememberedPageSize('jobs')).toBe(DEFAULT_PAGE_SIZES.jobs);
		} finally {
			Object.defineProperty(globalThis, 'localStorage', storage);
		}
	});
});
