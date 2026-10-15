/** Field values between the API's form and the text a form field holds. */
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';

export type ApiValue = components['schemas']['DocumentDetails']['fields'][string];
export type FieldType = components['schemas']['FieldType'];
/** Text for most types; `true`/`false`/'' for yes/no; amount and currency for money. */
export type InputValue = string | { amount: string; currency: string };

export const DEFAULT_CURRENCY = 'EUR';

/** The data types of a field definition, in the order the field dialog offers them. */
export const FIELD_TYPES: readonly FieldType[] = [
	'text',
	'number',
	'amount',
	'date',
	'boolean',
	'choice',
	'link'
];

const TYPE_LABELS: Record<FieldType, () => string> = {
	text: m.field_def_type_text,
	number: m.field_def_type_number,
	amount: m.field_def_type_amount,
	date: m.field_def_type_date,
	boolean: m.field_def_type_boolean,
	choice: m.field_def_type_choice,
	link: m.field_def_type_link
};

export function fieldTypeLabel(type: FieldType): string {
	return TYPE_LABELS[type]();
}

export function emptyValue(type: FieldType): InputValue {
	return type === 'amount' ? { amount: '', currency: DEFAULT_CURRENCY } : '';
}

export function toInput(type: FieldType, value: ApiValue | undefined): InputValue {
	if (value === undefined || value === null) return emptyValue(type);
	if (type === 'amount' && typeof value === 'object') return { ...value };
	if (type === 'boolean') return value === true ? 'true' : value === false ? 'false' : '';
	return String(value);
}

/** The value for the API, or null when the field is empty (which removes the value). */
export function toApi(type: FieldType, value: InputValue): ApiValue | null {
	if (type === 'amount') {
		const money = typeof value === 'object' ? value : { amount: '', currency: DEFAULT_CURRENCY };
		const amount = money.amount.trim().replace(',', '.');
		return amount === '' ? null : { amount, currency: money.currency.trim().toUpperCase() };
	}
	const text = typeof value === 'string' ? value.trim() : '';
	if (text === '') return null;
	if (type === 'boolean') return text === 'true';
	if (type === 'number') return text.replace(',', '.');
	return text;
}

/** Equal values, so that an untouched field does not end up in a change. */
export function sameValue(a: ApiValue | null | undefined, b: ApiValue | null | undefined): boolean {
	return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
}
