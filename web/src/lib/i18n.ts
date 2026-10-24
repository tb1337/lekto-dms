/**
 * Language of the UI and formats of dates and numbers. Paraglide picks the language: the choice
 * stored in this browser, else the browser's language, else English. Texts live in
 * `messages/{de,en}.json`; reasons the API gives with a code are translated (`reasons.ts`),
 * its other texts (problem details) stay as the API sends them.
 */
import { isIsoDay, localDay } from '#lib/dates.ts';
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

/**
 * A date (and optionally time) in the user's format. A day (`2026-10-01`) stays that calendar
 * day in every time zone; a moment is shown in the browser's time. Text that is no date comes
 * back as it is.
 */
export function formatDate(
	value: Date | string,
	options: Intl.DateTimeFormatOptions = { dateStyle: 'medium' }
): string {
	const date =
		typeof value !== 'string' ? value : isIsoDay(value) ? localDay(value) : new Date(value);
	if (Number.isNaN(date.getTime())) return typeof value === 'string' ? value : '';
	return new Intl.DateTimeFormat(formatLocale(), options).format(date);
}

/** The time of day of a moment, to the second (`14:05:09`). */
export function formatTime(value: Date | string): string {
	return formatDate(value, { timeStyle: 'medium' });
}

/** A number in the user's format. */
export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
	return new Intl.NumberFormat(formatLocale(), options).format(value);
}

/** A share (0 to 1) as whole percent (`87 %`). */
export function formatPercent(value: number): string {
	return formatNumber(value, { style: 'percent', maximumFractionDigits: 0 });
}

/**
 * An amount of money; `amount` is the API's exact decimal text, `currency` an ISO 4217 code.
 * A currency the browser does not know as a code is written plainly after the amount.
 */
export function formatMoney(amount: string, currency: string): string {
	try {
		return new Intl.NumberFormat(formatLocale(), { style: 'currency', currency }).format(
			Number(amount)
		);
	} catch {
		return `${formatNumber(Number(amount), { minimumFractionDigits: 2 })} ${currency}`;
	}
}
