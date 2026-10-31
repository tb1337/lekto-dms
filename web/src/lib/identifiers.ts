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

/** The kinds of a contact's identifiers, in the order the contact dialog offers them. */
export const IDENTIFIER_KINDS: readonly IdentifierKind[] = [
	'iban',
	'vat_id',
	'customer_number',
	'contract_number',
	'policy_number',
	'membership_number',
	'personnel_number',
	'email_domain',
	'creditor_id',
	'commercial_register',
	'tax_number',
	'meter_number',
	'loan_number',
	'mandate_reference',
	'license_plate'
];

/** The kinds of a person's own identifiers (a user's profile). */
export const PERSON_KINDS: readonly IdentifierKind[] = [
	'iban',
	'tax_id',
	'social_security_number',
	'health_insurance_number',
	'email_address',
	'child_benefit_number'
];

/** The kinds of a contact's identifiers that may name the user they belong to. */
export const NAMING_KINDS: readonly IdentifierKind[] = [
	'customer_number',
	'personnel_number',
	'contract_number',
	'policy_number',
	'membership_number',
	'meter_number',
	'loan_number',
	'mandate_reference',
	'license_plate',
	'tax_number'
];

/** The kinds of a document's numbers that are no contact's or person's identifier. */
export const NUMBER_KINDS: readonly IdentifierKind[] = [
	'invoice_number',
	'credit_note_number',
	'order_number',
	'file_reference',
	'our_reference',
	'claim_number',
	'ticket_number',
	'your_reference',
	'letter_date'
];

/** The label of a kind as the log or a candidate names it; a kind this UI does not know stays
 * as written. */
export function labelOfKind(kind: string): string {
	const known: readonly string[] = [...IDENTIFIER_KINDS, ...PERSON_KINDS, ...NUMBER_KINDS];
	return known.includes(kind) ? kindLabel(kind as IdentifierKind) : kind;
}

const KIND_LABELS: Record<IdentifierKind, () => string> = {
	iban: m.identifier_kind_iban,
	vat_id: m.identifier_kind_vat_id,
	customer_number: m.identifier_kind_customer_number,
	personnel_number: m.identifier_kind_personnel_number,
	email_domain: m.identifier_kind_email_domain,
	tax_id: m.identifier_kind_tax_id,
	social_security_number: m.identifier_kind_social_security_number,
	health_insurance_number: m.identifier_kind_health_insurance_number,
	email_address: m.identifier_kind_email_address,
	creditor_id: m.identifier_kind_creditor_id,
	commercial_register: m.identifier_kind_commercial_register,
	tax_number: m.identifier_kind_tax_number,
	contract_number: m.identifier_kind_contract_number,
	policy_number: m.identifier_kind_policy_number,
	membership_number: m.identifier_kind_membership_number,
	meter_number: m.identifier_kind_meter_number,
	loan_number: m.identifier_kind_loan_number,
	mandate_reference: m.identifier_kind_mandate_reference,
	license_plate: m.identifier_kind_license_plate,
	invoice_number: m.identifier_kind_invoice_number,
	credit_note_number: m.identifier_kind_credit_note_number,
	order_number: m.identifier_kind_order_number,
	file_reference: m.identifier_kind_file_reference,
	our_reference: m.identifier_kind_our_reference,
	your_reference: m.identifier_kind_your_reference,
	letter_date: m.identifier_kind_letter_date,
	claim_number: m.identifier_kind_claim_number,
	ticket_number: m.identifier_kind_ticket_number,
	child_benefit_number: m.identifier_kind_child_benefit_number
};

export function kindLabel(kind: IdentifierKind): string {
	return KIND_LABELS[kind]();
}

/** An identifier's value as it is printed: an IBAN in groups of four, other values as they are
 * kept. Wherever one is shown; an input holds it as kept. */
export function printed(kind: string, value: string): string {
	return kind === 'iban' ? value.replace(/\s+/g, '').replace(/(.{4})(?=.)/g, '$1 ') : value;
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
