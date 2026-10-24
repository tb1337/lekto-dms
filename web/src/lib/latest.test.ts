import { describe, expect, it } from 'vitest';
import { latest } from './latest.ts';

describe('latest', () => {
	it('counts only the newest call as current', () => {
		const begin = latest();
		const first = begin();
		expect(first()).toBe(true);
		const second = begin();
		expect(first()).toBe(false);
		expect(second()).toBe(true);
	});
});
