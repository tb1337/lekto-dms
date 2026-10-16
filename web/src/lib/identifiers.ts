/** Identifiers of contacts as the contact dialog edits them. */
import type { components } from '#lib/api/schema.ts';
import { m } from '#lib/paraglide/messages.js';

export type IdentifierIn = components['schemas']['IdentifierIn'];
export type IdentifierOut = components['schemas']['IdentifierOut'];
export type IdentifierKind = IdentifierIn['kind'];
export type IdentifierSource = IdentifierOut['source'];

export const IDENTIFIER_KINDS: readonly IdentifierKind[] = [
	'iban',
	'vat_id',
	'customer_number',
	'personnel_number',
	'email_domain'
];

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
	}
}

/** One row of the editor; `key` keeps a row apart while its value is typed. */
export interface IdentifierRow {
	key: number;
	kind: IdentifierKind;
	value: string;
	source: IdentifierSource;
}

let next = 0;

export function row(
	kind: IdentifierKind = 'iban',
	value = '',
	source: IdentifierSource = 'manual'
): IdentifierRow {
	return { key: next++, kind, value, source };
}

export function rowsOf(identifiers: readonly IdentifierOut[] | undefined): IdentifierRow[] {
	return (identifiers ?? []).map((item) => row(item.kind, item.value, item.source));
}

/** What a change sends: the identifiers entered by hand (a learned one taken over among them)
 * and the rejected ones; learned ones stay as they are. Empty rows are left out. */
export function changesOf(rows: readonly IdentifierRow[]): {
	identifiers: IdentifierIn[];
	rejected_identifiers: IdentifierIn[];
} {
	const pick = (source: IdentifierSource) =>
		rows
			.filter((item) => item.source === source && item.value.trim() !== '')
			.map((item) => ({ kind: item.kind, value: item.value.trim() }));
	return { identifiers: pick('manual'), rejected_identifiers: pick('rejected') };
}
