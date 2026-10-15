/**
 * Language of the UI and formats of dates and numbers. Paraglide picks the language: the choice
 * stored in this browser, else the browser's language, else English. Texts live in
 * `messages/{de,en}.json`; texts of the API (problem details) stay as the API sends them.
 */
import { m } from '#lib/paraglide/messages.js';
import { getLocale, locales, setLocale, type Locale } from '#lib/paraglide/runtime.js';

export { getLocale, locales, type Locale };

/** Each language in its own words, for the language switch. */
export const LANGUAGE_NAMES: Record<Locale, string> = { de: 'Deutsch', en: 'English' };

const DEFAULT_REGION: Record<Locale, string> = { de: 'de-DE', en: 'en-US' };

/** Switch the language; the page reloads in it and the choice stays in this browser. */
export function changeLanguage(locale: Locale): void {
	if (locale !== getLocale()) setLocale(locale);
}

/**
 * The locale for formats: the browser's own regional variant of the UI language if it has one
 * (`en-GB` for English in Britain), else German as in Germany or English as in the US.
 */
export function regionalLocale(
	locale: Locale,
	preferred: readonly string[] = typeof navigator === 'undefined' ? [] : navigator.languages
): string {
	const own = preferred.find((tag) => tag.toLowerCase().startsWith(`${locale}-`));
	return own ?? DEFAULT_REGION[locale];
}

function formatLocale(): string {
	return regionalLocale(getLocale());
}

/** A date (and optionally time) in the user's format. */
export function formatDate(
	value: Date | string,
	options: Intl.DateTimeFormatOptions = { dateStyle: 'medium' }
): string {
	const date = typeof value === 'string' ? new Date(value) : value;
	return new Intl.DateTimeFormat(formatLocale(), options).format(date);
}

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

/** A period as it is written: `September 2026`, `KW 38 2026`, `Q3 2026`, `2026`, a day, else
 * its ends (`01.–14.09.2026`). */
export function formatPeriod(start: string, end: string): string {
	const first = utcDay(start);
	const last = utcDay(end);
	const format = (options: Intl.DateTimeFormatOptions) =>
		new Intl.DateTimeFormat(formatLocale(), { ...options, timeZone: 'UTC' });
	switch (periodKind(start, end)) {
		case 'day':
			return format({ dateStyle: 'medium' }).format(first);
		case 'week': {
			const [week, year] = isoWeek(first);
			return m.period_week({ week: String(week), year: String(year) });
		}
		case 'month':
			return format({ month: 'long', year: 'numeric' }).format(first);
		case 'quarter':
			return m.period_quarter({
				quarter: String(first.getUTCMonth() / 3 + 1),
				year: String(first.getUTCFullYear())
			});
		case 'year':
			return String(first.getUTCFullYear());
		case 'span':
			return format({ dateStyle: 'medium' }).formatRange(first, last);
	}
}

/** A number in the user's format. */
export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
	return new Intl.NumberFormat(formatLocale(), options).format(value);
}

/** An amount of money; `amount` is the API's exact decimal text, `currency` an ISO 4217 code. */
export function formatMoney(amount: string, currency: string): string {
	return new Intl.NumberFormat(formatLocale(), { style: 'currency', currency }).format(
		Number(amount)
	);
}
