/**
 * Days as the API writes them (`YYYY-MM-DD`) and the small helpers around them. A day has no
 * time zone: read as a calendar day it stays the same day everywhere, which `new Date(day)`
 * (midnight UTC) does not guarantee west of Greenwich.
 */

export const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** Whether `text` is a `YYYY-MM-DD` day. */
export function isIsoDay(text: string): boolean {
	return ISO_DAY.test(text);
}

/** `7` as `07`. */
export function pad2(value: number): string {
	return String(value).padStart(2, '0');
}

/** The day at midnight in the browser's time: shown, it stays the same calendar day. */
export function localDay(day: string): Date {
	const [year, month, date] = day.split('-').map(Number);
	return new Date(year, month - 1, date);
}

/** The day at midnight UTC: for arithmetic on days, which no time zone then moves. */
export function utcDay(day: string): Date {
	const [year, month, date] = day.split('-').map(Number);
	return new Date(Date.UTC(year, month - 1, date));
}

/** The ISO day of `at` in the browser's time. */
export function isoDayLocal(at: Date): string {
	return `${at.getFullYear()}-${pad2(at.getMonth() + 1)}-${pad2(at.getDate())}`;
}

/** The ISO day of a UTC time. */
export function isoDayUtc(at: Date | number): string {
	return new Date(at).toISOString().slice(0, 10);
}

/** The number of the last day of a month (`month` 1 to 12). */
export function lastDayOfMonth(year: number, month: number): number {
	return new Date(Date.UTC(year, month, 0)).getUTCDate();
}
