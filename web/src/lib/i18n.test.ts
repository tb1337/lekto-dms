import { describe, expect, it } from 'vitest';
import { formatPeriod, periodKind, regionalLocale } from './i18n.ts';

describe('regionalLocale', () => {
	it("takes the browser's region for the UI language", () => {
		expect(regionalLocale('en', ['de-DE', 'en-GB', 'en'])).toBe('en-GB');
		expect(regionalLocale('de', ['de-AT', 'en-US'])).toBe('de-AT');
		expect(regionalLocale('de', ['DE-ch'])).toBe('DE-ch');
	});

	it('falls back to Germany and the US', () => {
		expect(regionalLocale('de', ['en-GB', 'de'])).toBe('de-DE');
		expect(regionalLocale('en', [])).toBe('en-US');
	});

	it('does not take a language that merely starts alike', () => {
		expect(regionalLocale('de', ['dev-XX'])).toBe('de-DE');
	});
});

describe('periods', () => {
	it('are what their ends make them', () => {
		expect(periodKind('2026-09-15', '2026-09-15')).toBe('day');
		expect(periodKind('2026-09-14', '2026-09-20')).toBe('week');
		expect(periodKind('2026-09-15', '2026-09-21')).toBe('span'); // Tuesday to Monday
		expect(periodKind('2028-02-01', '2028-02-29')).toBe('month');
		expect(periodKind('2026-07-01', '2026-09-30')).toBe('quarter');
		expect(periodKind('2026-02-01', '2026-04-30')).toBe('span');
		expect(periodKind('2025-01-01', '2025-12-31')).toBe('year');
	});

	it('are written as they are', () => {
		expect(formatPeriod('2026-09-01', '2026-09-30')).toBe('September 2026');
		expect(formatPeriod('2026-09-14', '2026-09-20')).toBe('Week 38, 2026');
		expect(formatPeriod('2026-12-28', '2027-01-03')).toBe('Week 53, 2026');
		expect(formatPeriod('2026-07-01', '2026-09-30')).toBe('Q3 2026');
		expect(formatPeriod('2025-01-01', '2025-12-31')).toBe('2025');
		expect(formatPeriod('2026-09-15', '2026-09-15')).toBe('Sep 15, 2026');
		const span = formatPeriod('2026-09-01', '2026-09-14');
		expect(span).toContain('1');
		expect(span).toContain('14');
		expect(span).toContain('2026');
	});
});
