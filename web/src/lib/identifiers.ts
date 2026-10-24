/** Identifiers of contacts as the contact dialog edits them, and of persons as the profile
 * does. */
import { ApiError } from '#lib/api/problem.ts';
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';

export type IdentifierIn = components['schemas']['IdentifierIn'];
export type IdentifierOut = components['schemas']['IdentifierOut'];
export type ContactNumberIn = components['schemas']['ContactNumberIn'];
export type ContactNumberOut = components['schemas']['ContactNumberOut'];
export type IdentifierKind = IdentifierIn['kind'];
export type IdentifierSource = IdentifierOut['source'];

export const IDENTIFIER_KINDS: readonly IdentifierKind[] = [
	'iban',
	'vat_id',
	'customer_number',
	'personnel_number',
	'email_domain'
];

/** The kinds of a person's own identifiers (a user's profile). */
export const PERSON_KINDS: readonly IdentifierKind[] = [
	'iban',
	'tax_id',
	'social_security_number',
	'health_insurance_number',
	'email_address'
];

/** The kinds of a contact's identifiers that may name the user they belong to. */
export const NAMING_KINDS: readonly IdentifierKind[] = ['customer_number', 'personnel_number'];

/** The label of a kind as the log or a candidate names it; a kind this UI does not know stays
 * as written. */
export function labelOfKind(kind: string): string {
	const known: readonly string[] = [...IDENTIFIER_KINDS, ...PERSON_KINDS];
	return known.includes(kind) ? kindLabel(kind as IdentifierKind) : kind;
}

export function kindLabel(kind: IdentifierKind): string {
	switch (kind) {
		case 'iban':
			return m.identifier_kind_iban();
		case 'vat_id':
			return m.identifier_kind_vat_id();
		case 'customer_number':
			return m.identifier_kind_customer_number();
		case 'personnel_number':
			return m.identifier_kind_personnel_number();
		case 'email_domain':
			return m.identifier_kind_email_domain();
		case 'tax_id':
			return m.identifier_kind_tax_id();
		case 'social_security_number':
			return m.identifier_kind_social_security_number();
		case 'health_insurance_number':
			return m.identifier_kind_health_insurance_number();
		case 'email_address':
			return m.identifier_kind_email_address();
	}
}

/** One row of the editor; `key` keeps a row apart while its value is typed. `topic_id`: the
 * contact's topic it points to (empty: none); `user_id`: the user a customer or personnel number
 * belongs to (empty: none); `contact_id`: the contact of a user's number (the profile; empty:
 * none chosen yet). */
export interface IdentifierRow {
	key: number;
	kind: IdentifierKind;
	value: string;
	source: IdentifierSource;
	topic_id: string;
	user_id: string;
	contact_id: string;
}

let next = 0;

export function row(
	kind: IdentifierKind = 'iban',
	value = '',
	source: IdentifierSource = 'manual',
	topic_id: string | null = null,
	user_id: string | null = null,
	contact_id: string | null = null
): IdentifierRow {
	return {
		key: next++,
		kind,
		value,
		source,
		topic_id: topic_id ?? '',
		user_id: user_id ?? '',
		contact_id: contact_id ?? ''
	};
}

export function rowsOf(
	identifiers:
		| readonly (Pick<IdentifierOut, 'kind' | 'value'> &
				Partial<IdentifierOut> &
				Partial<Pick<ContactNumberOut, 'contact_id'>>)[]
		| undefined
): IdentifierRow[] {
	return (identifiers ?? []).map((item) =>
		row(
			item.kind,
			item.value,
			item.source ?? 'manual',
			item.topic_id,
			item.user_id,
			item.contact_id
		)
	);
}

/** What a profile sends of the user's numbers at contacts: those entered by hand (a learned one
 * taken over among them), each with its topic if its contact enables it (`topicsOf`), and the
 * learned ones declined; learned ones left alone stay. Rows without contact or value are left
 * out. */
export function numbersOf(
	rows: readonly IdentifierRow[],
	topicsOf: (contact: string) => readonly string[]
): { numbers: ContactNumberIn[]; declined_numbers: ContactNumberIn[] } {
	const filled = rows.filter((item) => item.value.trim() !== '' && item.contact_id !== '');
	const number = (item: IdentifierRow): ContactNumberIn => ({
		contact_id: item.contact_id,
		kind: item.kind,
		value: item.value.trim()
	});
	return {
		numbers: filled
			.filter((item) => item.source === 'manual')
			.map((item) =>
				item.topic_id !== '' && topicsOf(item.contact_id).includes(item.topic_id)
					? { ...number(item), topic_id: item.topic_id }
					: number(item)
			),
		declined_numbers: filled.filter((item) => item.source === 'rejected').map(number)
	};
}

/** What a change sends: the identifiers entered by hand (a learned one taken over among them),
 * each with its topic if it is one of `topics` (those the contact enables), and the rejected
 * ones; learned ones stay as they are. Empty rows are left out. */
export function changesOf(
	rows: readonly IdentifierRow[],
	topics?: readonly string[]
): {
	identifiers: IdentifierIn[];
	rejected_identifiers: IdentifierIn[];
} {
	const filled = rows.filter((item) => item.value.trim() !== '');
	const topicOf = (item: IdentifierRow) =>
		item.topic_id !== '' && (topics === undefined || topics.includes(item.topic_id))
			? { topic_id: item.topic_id }
			: {};
	const userOf = (item: IdentifierRow) =>
		item.user_id !== '' && NAMING_KINDS.includes(item.kind) ? { user_id: item.user_id } : {};
	return {
		identifiers: filled
			.filter((item) => item.source === 'manual')
			.map((item) => ({
				kind: item.kind,
				value: item.value.trim(),
				...topicOf(item),
				...userOf(item)
			})),
		rejected_identifiers: filled
			.filter((item) => item.source === 'rejected')
			.map((item) => ({ kind: item.kind, value: item.value.trim() }))
	};
}

/**
 * The row a refused change failed on: the identifier the problem's reason names
 * (`params.value`), or, for an error without a code, the row whose value its detail quotes.
 * Values compare without spaces and case: an IBAN as typed, the API's as stored.
 */
export function refusedRow(
	error: unknown,
	rows: readonly IdentifierRow[]
): IdentifierRow | undefined {
	if (!(error instanceof ApiError)) return undefined;
	const filled = rows.filter((item) => item.value.trim() !== '');
	const value = error.problem?.reason?.params.value;
	if (typeof value === 'string') {
		const plain = (text: string) => text.replace(/\s+/g, '').toLowerCase();
		return filled.find((item) => plain(item.value) === plain(value));
	}
	const detail = error.problem?.detail ?? '';
	return filled.find((item) => detail.includes(`'${item.value.trim()}'`));
}
