import { describe, expect, it } from 'vitest';
import { formatDuration } from './duration.ts';

const NBSP = ' ';

describe('formatDuration', () => {
	it('puts the unit right after the number', () => {
		expect(formatDuration(0.04)).toBe('0s');
		expect(formatDuration(4.24)).toBe('4.2s');
		expect(formatDuration(9.99)).toBe('10s');
		expect(formatDuration(48.4)).toBe('48s');
	});

	it('takes minutes and seconds, then hours and minutes, never broken apart', () => {
		expect(formatDuration(63)).toBe(`1m${NBSP}3s`);
		expect(formatDuration(154)).toBe(`2m${NBSP}34s`);
		expect(formatDuration(59.6)).toBe(`1m${NBSP}0s`);
		expect(formatDuration(7500)).toBe(`2h${NBSP}5m`);
		expect(formatDuration(-3)).toBe('0s');
	});
});
