import { afterEach, describe, expect, it } from 'vitest';
import { formatDate, formatMoney, regionalLocale } from './i18n.ts';

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

describe('formatDate', () => {
	const zone = process.env.TZ;
	afterEach(() => {
		process.env.TZ = zone;
	});

	it('keeps a day the same calendar day west of Greenwich', () => {
		process.env.TZ = 'America/New_York';
		expect(formatDate('2026-10-01', { day: 'numeric', month: 'numeric', year: 'numeric' })).toBe(
			'10/1/2026'
		);
	});

	it('shows a moment in the browser time', () => {
		process.env.TZ = 'Europe/Berlin';
		expect(formatDate('2026-10-01T23:30:00Z', { dateStyle: 'short', timeStyle: 'short' })).toBe(
			'10/2/26, 1:30 AM'
		);
	});

	it('returns text that is no date as it is', () => {
		expect(formatDate('yesterday')).toBe('yesterday');
	});
});

describe('formatMoney', () => {
	it('writes a known currency as the browser does', () => {
		expect(formatMoney('12.5', 'EUR')).toBe('€12.50');
	});

	it('writes an unknown currency plainly instead of failing', () => {
		expect(formatMoney('12.5', 'EURO')).toBe('12.50 EURO');
	});
});
