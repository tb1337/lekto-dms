import { afterEach, describe, expect, it } from 'vitest';
import {
	isIsoDay,
	isoDayLocal,
	isoDayUtc,
	lastDayOfMonth,
	localDay,
	pad2,
	utcDay
} from './dates.ts';

const zone = process.env.TZ;
afterEach(() => {
	process.env.TZ = zone;
});

describe('days', () => {
	it('recognises a day', () => {
		expect(isIsoDay('2026-10-01')).toBe(true);
		expect(isIsoDay('2026-10-01T00:00:00Z')).toBe(false);
		expect(isIsoDay('2026-10')).toBe(false);
	});

	it('pads to two digits', () => {
		expect(pad2(7)).toBe('07');
		expect(pad2(12)).toBe('12');
	});

	it('keeps the calendar day west of Greenwich', () => {
		process.env.TZ = 'America/New_York';
		const day = localDay('2026-10-01');
		expect([day.getFullYear(), day.getMonth(), day.getDate()]).toEqual([2026, 9, 1]);
		expect(isoDayLocal(day)).toBe('2026-10-01');
	});

	it('reads and writes a day in UTC', () => {
		expect(utcDay('2026-10-01').toISOString()).toBe('2026-10-01T00:00:00.000Z');
		expect(isoDayUtc(Date.UTC(2026, 9, 1, 23))).toBe('2026-10-01');
	});

	it('knows the last day of a month', () => {
		expect(lastDayOfMonth(2026, 2)).toBe(28);
		expect(lastDayOfMonth(2028, 2)).toBe(29);
		expect(lastDayOfMonth(2026, 12)).toBe(31);
	});
});
