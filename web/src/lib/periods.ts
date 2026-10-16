/**
 * Periods (a field type): spans of days, both ends included, as `YYYY-MM-DD` start and end.
 * They are written in ISO 8601, a quarter as is usual (ISO has no short form for it): `2026`,
 * `2026-Q2`, `2026-03`, `2026-W17`, a day as `2026-03-31`, else its ends,
 * `2026-03-01/2026-03-14`. Read are these forms and the German ones (`KW 17/2026`, `Q2 2026`,
 * `03/2026`, `März 2026`, `31.03.2026`), and a span of any two (`01.03.2026–14.03.2026`).
 */
import type { Period } from '#lib/fields.ts';

/** What a period is, by its ends (as the API's `PeriodKind`). */
export type PeriodKind = 'day' | 'week' | 'month' | 'quarter' | 'year' | 'span';

const DAY = 86_400_000;

/** A `YYYY-MM-DD` day at midnight UTC, so no time zone moves it. */
function utcDay(day: string): Date {
	const [year, month, date] = day.split('-').map(Number);
	return new Date(Date.UTC(year, month - 1, date));
}

function lastOfMonth(year: number, month: number): number {
	return Date.UTC(year, month + 1, 0);
}

function isoDay(time: number): string {
	return new Date(time).toISOString().slice(0, 10);
}

export function periodKind(start: string, end: string): PeriodKind {
	const first = utcDay(start);
	const last = utcDay(end).getTime();
	const [year, month] = [first.getUTCFullYear(), first.getUTCMonth()];
	if (last === first.getTime()) return 'day';
	if (first.getUTCDay() === 1 && last === first.getTime() + 6 * DAY) return 'week';
	if (first.getUTCDate() === 1) {
		if (last === lastOfMonth(year, month)) return 'month';
		if (month % 3 === 0 && last === lastOfMonth(year, month + 2)) return 'quarter';
		if (month === 0 && last === Date.UTC(year, 11, 31)) return 'year';
	}
	return 'span';
}

/** ISO 8601 week and its year: the week with the year's first Thursday is week 1. */
function isoWeek(day: Date): [number, number] {
	const thursday = new Date(day.getTime() + (3 - ((day.getUTCDay() + 6) % 7)) * DAY);
	const year = thursday.getUTCFullYear();
	return [Math.floor((thursday.getTime() - Date.UTC(year, 0, 1)) / DAY / 7) + 1, year];
}

const two = (value: number) => String(value).padStart(2, '0');

/** A period in ISO 8601 (`2026-W17`, `2026-Q2`, …); empty while an end is missing. */
export function writePeriod(start: string, end: string): string {
	if (!isDay(start) || !isDay(end) || end < start) return '';
	const first = utcDay(start);
	switch (periodKind(start, end)) {
		case 'day':
			return start;
		case 'week': {
			const [week, year] = isoWeek(first);
			return `${year}-W${two(week)}`;
		}
		case 'month':
			return start.slice(0, 7);
		case 'quarter':
			return `${start.slice(0, 4)}-Q${first.getUTCMonth() / 3 + 1}`;
		case 'year':
			return start.slice(0, 4);
		case 'span':
			return `${start}/${end}`;
	}
}

function isDay(text: string): boolean {
	return /^\d{4}-\d{2}-\d{2}$/.test(text);
}

function day(year: number, month: number, date: number): Period | null {
	const time = Date.UTC(year, month - 1, date);
	const found = new Date(time);
	if (found.getUTCMonth() !== month - 1 || found.getUTCDate() !== date) return null;
	return { start: isoDay(time), end: isoDay(time) };
}

function week(year: number, number: number): Period | null {
	const fourth = Date.UTC(year, 0, 4); // always in week 1
	const monday = fourth - ((new Date(fourth).getUTCDay() + 6) % 7) * DAY + (number - 1) * 7 * DAY;
	const [found] = isoWeek(new Date(monday));
	if (number < 1 || found !== number) return null; // week 53 of a year with 52
	return { start: isoDay(monday), end: isoDay(monday + 6 * DAY) };
}

function month(year: number, number: number): Period | null {
	if (number < 1 || number > 12) return null;
	return {
		start: isoDay(Date.UTC(year, number - 1, 1)),
		end: isoDay(lastOfMonth(year, number - 1))
	};
}

function quarter(year: number, number: number): Period {
	const first = (number - 1) * 3;
	return { start: isoDay(Date.UTC(year, first, 1)), end: isoDay(lastOfMonth(year, first + 2)) };
}

/** Month names to read: German and English, without umlauts (`Maerz`), any three or more
 * letters of one (`Sept`, `Mär`). */
const MONTH_NAMES = [
	['januar', 'january'],
	['februar', 'february'],
	['maerz', 'march'],
	['april'],
	['mai', 'may'],
	['juni', 'june'],
	['juli', 'july'],
	['august'],
	['september'],
	['oktober', 'october'],
	['november'],
	['dezember', 'december']
];

function monthOf(word: string): number | null {
	const plain = word.toLowerCase().replace(/ä/g, 'ae').replace(/\.$/, '');
	if (plain.length < 3) return null;
	const index = MONTH_NAMES.findIndex((names) => names.some((name) => name.startsWith(plain)));
	return index < 0 ? null : index + 1;
}

const FORMS: [RegExp, (found: string[]) => Period | null][] = [
	// ISO 8601: 2026-03-31, 2026-W17, 2026-03, 2026-Q2, 2026
	[/^(\d{4})-(\d{2})-(\d{2})$/, ([, y, mo, d]) => day(+y, +mo, +d)],
	[/^(\d{4})-?w(\d{1,2})$/i, ([, y, w]) => week(+y, +w)],
	[/^(\d{4})-(\d{2})$/, ([, y, mo]) => month(+y, +mo)],
	[/^(\d{4})\s*-?\s*q([1-4])$/i, ([, y, q]) => quarter(+y, +q)],
	[/^(\d{4})$/, ([, y]) => ({ start: `${y}-01-01`, end: `${y}-12-31` })],
	// German: 31.03.2026, KW 17/2026, Q2 2026, 03/2026, März 2026
	[/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/, ([, d, mo, y]) => day(+y, +mo, +d)],
	[/^(?:kw|w|week|woche)\s*(\d{1,2})\s*[/,.\s]\s*(\d{4})$/i, ([, w, y]) => week(+y, +w)],
	[/^q([1-4])\s*[/\s-]?\s*(\d{4})$/i, ([, q, y]) => quarter(+y, +q)],
	[/^(\d{1,2})\s*[/.]\s*(\d{4})$/, ([, mo, y]) => month(+y, +mo)],
	[
		/^(\p{L}+\.?)\s*[/\s]\s*(\d{4})$/u,
		([, name, y]) => {
			const number = monthOf(name);
			return number === null ? null : month(+y, number);
		}
	]
];

function readOne(text: string): Period | null {
	for (const [form, read] of FORMS) {
		const found = form.exec(text);
		if (found) return read(found);
	}
	return null;
}

// Between the two ends of a span: `/`, a dash with or without spaces, `bis`, `to`.
const BETWEEN = /\s*\/\s*|\s*[–—]\s*|\s+-\s+|\s+(?:bis|to)\s+/gi;

/** The period `text` writes in one of the forms above, or null. */
export function readPeriod(text: string): Period | null {
	const plain = text.trim().replace(/\s+/g, ' ');
	if (plain === '') return null;
	const whole = readOne(plain);
	if (whole) return whole;
	// A span: the first period's start to the second's end, at the first cut that reads.
	for (const cut of plain.matchAll(BETWEEN)) {
		const first = readOne(plain.slice(0, cut.index));
		const second = readOne(plain.slice(cut.index + cut[0].length));
		if (first && second && first.start <= second.end)
			return { start: first.start, end: second.end };
	}
	return null;
}
