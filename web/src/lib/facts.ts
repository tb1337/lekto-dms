/**
 * What a document shows of its contact (`GET /documents/{id}/facts`): names and identifiers
 * with where they stand in the text and on the pages, and the codes on the pages. Spans count
 * characters (code points) of the whole text, as `GET /documents/{id}/text` does; the text view
 * counts in JavaScript's units and splits the text into pages.
 */
import type { components } from '#lib/api/schema.ts';
import type { Mark } from '#lib/document-view.ts';
import { type IdentifierKind, kindLabel } from '#lib/identifiers.ts';
import { m } from '#lib/paraglide/messages.js';

export type Facts = components['schemas']['FactsOut'];
export type FoundIdentifier = components['schemas']['FoundIdentifierOut'];
export type NamedContact = components['schemas']['NamedContactOut'];
export type CodeFacts = components['schemas']['CodeOut'];
export type CodePlace = components['schemas']['CodePlaceOut'];
export type Span = components['schemas']['SpanOut'];
export type FoundPerson = components['schemas']['FoundPersonOut'];
export type DocumentNumber = components['schemas']['DocumentNumberOut'];
export type Strength = FoundPerson['strength'];
export type FactRole = components['schemas']['FactRole'];
export type FactState = components['schemas']['FactState'];
export type FactOrigin = components['schemas']['FactOrigin'];
type FactDecisionIn = components['schemas']['FactDecisionIn'];
/** A person's decision about a fact (`POST /documents/{id}/facts/decisions`), with what the
 * action needs only. */
export type FactDecision = Pick<FactDecisionIn, 'action' | 'kind' | 'value'> &
	Partial<Pick<FactDecisionIn, 'role' | 'new_value' | 'at_contact'>>;

/** A fact kept for the document, as the pane shows and decides about it. */
export interface KeptFact {
	kind: IdentifierKind;
	value: string;
	written?: string | null;
	role: FactRole;
	origins: readonly FactOrigin[];
	state?: FactState;
}

/** The roles a person gives a fact, in the order the forms offer them. */
export const FACT_ROLES: readonly FactRole[] = [
	'contact',
	'target',
	'own',
	'thread',
	'refers',
	'person'
];

/** The role of a fact of each kind until a source tells (`x-fact-roles`): a fact added gets it
 * unless the person chooses another. */
export const KIND_ROLES: Record<IdentifierKind, FactRole> = {
	iban: 'contact',
	vat_id: 'contact',
	customer_number: 'contact',
	personnel_number: 'contact',
	email_domain: 'contact',
	tax_id: 'person',
	social_security_number: 'person',
	health_insurance_number: 'person',
	email_address: 'person',
	creditor_id: 'contact',
	commercial_register: 'contact',
	tax_number: 'contact',
	contract_number: 'target',
	policy_number: 'target',
	membership_number: 'target',
	meter_number: 'target',
	loan_number: 'target',
	mandate_reference: 'target',
	license_plate: 'target',
	invoice_number: 'own',
	credit_note_number: 'own',
	order_number: 'own',
	file_reference: 'thread',
	our_reference: 'thread',
	claim_number: 'thread',
	ticket_number: 'thread',
	your_reference: 'refers',
	letter_date: 'refers',
	child_benefit_number: 'person'
};

/** Whether only a person gave the fact: withdrawing the decision removes it. */
export function onlyByPerson(fact: KeptFact): boolean {
	return fact.origins.every((origin) => origin === 'person');
}

/** A person's decision about a fact, in words ("rejected"); nothing for one as found. */
export function stateLabel(state: FactState | undefined): string | null {
	switch (state) {
		case 'added':
			return m.facts_state_added();
		case 'corrected':
			return m.facts_state_corrected();
		case 'rejected':
			return m.facts_state_rejected();
		default:
			return null;
	}
}

const ROLE_LABELS: Record<FactRole, () => string> = {
	contact: m.fact_role_contact,
	target: m.fact_role_target,
	own: m.fact_role_own,
	thread: m.fact_role_thread,
	refers: m.fact_role_refers,
	person: m.fact_role_person
};

/** What a fact is to the document, in words ("points to the contact"). */
export function roleLabel(role: FactRole): string {
	return ROLE_LABELS[role]();
}

/** How surely the document names a person, in words. */
export function strengthLabel(strength: Strength): string {
	switch (strength) {
		case 'hard':
			return m.facts_person_hard();
		case 'medium':
			return m.facts_person_medium();
		case 'weak':
			return m.facts_person_weak();
	}
}

/** A kind of evidence for a person, in words: a name, the birth date, a kind of identifier. */
export function evidenceLabel(kind: string): string {
	switch (kind) {
		case 'name':
			return m.facts_person_name();
		case 'alias':
			return m.facts_person_alias();
		case 'birth_date':
			return m.facts_person_birth_date();
		default:
			return kindLabel(kind as IdentifierKind);
	}
}

/** Characters `start` to `end` (exclusive) of the text, to mark there. */
export interface Stretch {
	start: number;
	end: number;
}

/** A stretch of a page's text, marked or not. */
export interface Segment {
	text: string;
	marked: boolean;
}

/** A form feed on a line of its own: how the text keeps its pages apart. */
export const PAGE_BREAK = /\n?\f\n?/;

/** Where each page of the text starts and ends: pages are apart by a form feed on a line of
 * its own, as the text view splits them. */
export function pageRanges(text: string): { start: number; end: number }[] {
	const ranges: { start: number; end: number }[] = [];
	const separator = new RegExp(PAGE_BREAK.source, 'g');
	let start = 0;
	for (let match = separator.exec(text); match !== null; match = separator.exec(text)) {
		ranges.push({ start, end: match.index });
		start = match.index + match[0].length;
	}
	ranges.push({ start, end: text.length });
	return ranges;
}

/** Spans in code points as spans in JavaScript's units of `text`. */
export function inUnits(text: string, spans: readonly Stretch[]): Stretch[] {
	if (spans.length === 0 || !/[\uD800-\uDBFF]/.test(text)) return [...spans];
	const units: number[] = [];
	let unit = 0;
	for (const char of text) {
		units.push(unit);
		unit += char.length;
	}
	units.push(unit);
	const at = (point: number) => units[Math.min(point, units.length - 1)];
	return spans.map((span) => ({ start: at(span.start), end: at(span.end) }));
}

/** The page's text from `start` to `end` of the whole text, in stretches, those within
 * `marks` (JavaScript's units of the whole text) marked. */
export function segmentsOf(
	text: string,
	range: { start: number; end: number },
	marks: readonly Stretch[]
): Segment[] {
	const inside = marks
		.map((mark) => ({
			start: Math.max(mark.start, range.start),
			end: Math.min(mark.end, range.end)
		}))
		.filter((mark) => mark.start < mark.end)
		.sort((a, b) => a.start - b.start);
	const segments: Segment[] = [];
	let at = range.start;
	for (const mark of inside) {
		if (mark.start < at) continue; // overlaps one before
		if (mark.start > at) segments.push({ text: text.slice(at, mark.start), marked: false });
		segments.push({ text: text.slice(mark.start, mark.end), marked: true });
		at = mark.end;
	}
	if (at < range.end) segments.push({ text: text.slice(at, range.end), marked: false });
	return segments;
}

/** Where a field's quote stands in `text`, in JavaScript's units: its words in order with any
 * spaces and line breaks between them, case aside. At most `most` places. */
export function quoteStretches(text: string, quote: string, most = 5): Stretch[] {
	const words = quote.split(/\s+/).filter(Boolean);
	if (words.length === 0) return [];
	const escaped = words.map((word) => word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
	const pattern = new RegExp(escaped.join('\\s+'), 'giu');
	const found: Stretch[] = [];
	for (const match of text.matchAll(pattern)) {
		found.push({ start: match.index, end: match.index + match[0].length });
		if (found.length === most) break;
	}
	return found;
}

/** The places on the pages of what `spans` mark, for the viewer, under `label`. */
export function spanMarks(spans: readonly Span[], label: string): Mark[] {
	return spans.flatMap((span, index) =>
		span.locations.map((place) => ({
			key: `fact:${index}`,
			label,
			page: place.page,
			boxes: place.boxes,
			derived: false,
			pinned: false
		}))
	);
}

/** An IBAN in groups of four, as it is printed; other values as they are kept. */
export function shown(item: Pick<FoundIdentifier, 'kind' | 'value'>): string {
	return item.kind === 'iban' ? item.value.replace(/(.{4})(?=.)/g, '$1 ') : item.value;
}

/** The key of an identifier, to tell rows apart and to find a code's in the text. */
export function identifierKey(item: Pick<FoundIdentifier, 'kind' | 'value'>): string {
	return `${item.kind}:${item.value}`;
}

/** Where the content of a code stands in the text too: its identifiers, and the payee of a
 * GiroCode that is named there. */
export function codeSpans(facts: Facts, code: CodeFacts): Span[] {
	const keys = new Set(code.identifiers.map(identifierKey));
	const identifiers = facts.identifiers
		.filter((item) => keys.has(identifierKey(item)))
		.flatMap((item) => item.spans);
	const payee = code.giro
		? facts.named.filter((item) => item.in_code && item.in_text).flatMap((item) => item.spans)
		: [];
	return [...identifiers, ...payee];
}

/** The facts in groups: those of the document's contact, those of other contacts, those of
 * none. */
export function grouped(facts: Facts): {
	own: (NamedContact | FoundIdentifier)[];
	others: (NamedContact | FoundIdentifier)[];
	unknown: FoundIdentifier[];
} {
	const mine = (contact: string | null | undefined) =>
		contact !== null && contact !== undefined && contact === facts.contact_id;
	const known = [...facts.named, ...facts.identifiers.filter((item) => item.contact_id)];
	return {
		own: known.filter((item) => mine(item.contact_id)),
		others: known.filter((item) => !mine(item.contact_id)),
		unknown: facts.identifiers.filter((item) => !item.contact_id)
	};
}

/** What the chip at the contact field counts. */
export function factCounts(facts: Facts): { evidence: number; unknown: number; codes: number } {
	const groups = grouped(facts);
	return {
		evidence: groups.own.length,
		unknown: groups.unknown.length,
		codes: facts.codes?.length ?? 0
	};
}

/** What there is, counted, in words (`1 Beleg · 2 Codes`); empty for nothing. */
export function factsSummary({ evidence, unknown, codes }: ReturnType<typeof factCounts>): string {
	const count = (n: number, one: () => string, many: (args: { count: number }) => string) =>
		n === 0 ? [] : [n === 1 ? one() : many({ count: n })];
	return [
		...count(evidence, m.facts_chip_evidence_one, m.facts_chip_evidence),
		...count(unknown, m.facts_chip_unknown_one, m.facts_chip_unknown),
		...count(codes, m.facts_chip_codes_one, m.facts_chip_codes)
	].join(' · ');
}
