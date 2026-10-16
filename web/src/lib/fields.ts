/** Field values between the API's form and the text a form field holds. */
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';

export type ApiValue = components['schemas']['DocumentDetails']['fields'][string];
export type FieldType = components['schemas']['FieldType'];
/** Text for most types; `true`/`false`/'' for yes/no; amount and currency for money; start
 * and end (`YYYY-MM-DD`) for a period. */
export type InputValue = string | { amount: string; currency: string } | Period;
export type Period = components['schemas']['PeriodValue'];
export type Money = components['schemas']['MoneyValue'];

export function isMoney(value: unknown): value is Money {
	return typeof value === 'object' && value !== null && 'amount' in value && 'currency' in value;
}

export function isPeriod(value: unknown): value is Period {
	return typeof value === 'object' && value !== null && 'start' in value && 'end' in value;
}

export const DEFAULT_CURRENCY = 'EUR';

/** The data types of a field definition, in the order the field dialog offers them. */
export const FIELD_TYPES: readonly FieldType[] = [
	'text',
	'number',
	'amount',
	'date',
	'boolean',
	'choice',
	'link',
	'period'
];

const TYPE_LABELS: Record<FieldType, () => string> = {
	text: m.field_def_type_text,
	number: m.field_def_type_number,
	amount: m.field_def_type_amount,
	date: m.field_def_type_date,
	boolean: m.field_def_type_boolean,
	choice: m.field_def_type_choice,
	link: m.field_def_type_link,
	period: m.field_def_type_period
};

export function fieldTypeLabel(type: FieldType): string {
	return TYPE_LABELS[type]();
}

export function emptyValue(type: FieldType): InputValue {
	if (type === 'amount') return { amount: '', currency: DEFAULT_CURRENCY };
	if (type === 'period') return { start: '', end: '' };
	return '';
}

export function toInput(type: FieldType, value: ApiValue | undefined): InputValue {
	if (value === undefined || value === null) return emptyValue(type);
	if (type === 'amount' && isMoney(value)) return { ...value };
	if (type === 'period' && isPeriod(value)) return { ...value };
	if (type === 'boolean') return value === true ? 'true' : value === false ? 'false' : '';
	return String(value);
}

/** The value for the API, or null when the field is empty (which removes the value). */
export function toApi(type: FieldType, value: InputValue): ApiValue | null {
	if (type === 'amount') {
		const money = isMoney(value) ? value : { amount: '', currency: DEFAULT_CURRENCY };
		const amount = money.amount.trim().replace(',', '.');
		return amount === '' ? null : { amount, currency: money.currency.trim().toUpperCase() };
	}
	if (type === 'period') {
		// One date given is that day.
		const start = isPeriod(value) ? value.start.trim() : '';
		const end = isPeriod(value) ? value.end.trim() : '';
		if (start === '' && end === '') return null;
		return { start: start || end, end: end || start };
	}
	const text = typeof value === 'string' ? value.trim() : '';
	if (text === '') return null;
	if (type === 'boolean') return text === 'true';
	if (type === 'number') return text.replace(',', '.');
	return text;
}

/** Equal values, so that an untouched field does not end up in a change. */
export function sameValue(a: ApiValue | null | undefined, b: ApiValue | null | undefined): boolean {
	return canonical(a ?? null) === canonical(b ?? null);
}

/** JSON with the keys of objects in order: `{start, end}` equals `{end, start}`. */
function canonical(value: unknown): string {
	return JSON.stringify(value, (_key, item: unknown) =>
		typeof item === 'object' && item !== null && !Array.isArray(item)
			? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b)))
			: item
	);
}
