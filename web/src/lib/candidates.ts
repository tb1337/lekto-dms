/**
 * What the signals proposed for a field (contact, document type, tags) and what each signal
 * said about a value, as chips in the review and behind the info icon of a green field.
 */
import type { components } from '#lib/api/schema.ts';
import { BASE } from '#lib/base.ts';
import { formatNumber } from '#lib/i18n.ts';
import { IDENTIFIER_KINDS, kindLabel, type IdentifierKind } from '#lib/identifiers.ts';
import { m } from '#lib/paraglide/messages.js';

export type Candidate = components['schemas']['CandidateOut'];
export type CandidateSource = components['schemas']['CandidateSourceOut'];
type Check = components['schemas']['FieldCheckOut'];

export interface SourceChip {
	text: string;
	/** It counts for the judge: a signal sure of the value, or evidence in the text. */
	strong: boolean;
	/** The passage the language model quoted. */
	quote: string | null;
	/** Similar documents that carry the value. */
	documents: string[];
}

const percent = (value: number) =>
	formatNumber(value, { style: 'percent', maximumFractionDigits: 0 });

function identifierLabel(kind: string): string {
	return (IDENTIFIER_KINDS as readonly string[]).includes(kind)
		? kindLabel(kind as IdentifierKind)
		: kind;
}

/** The chips of one signal's say: one, or for the facts one per identifier and the name. */
export function sourceChips(source: CandidateSource): SourceChip[] {
	const chip = (text: string, strong = source.names): SourceChip => ({
		text,
		strong,
		quote: null,
		documents: []
	});
	switch (source.signal) {
		case 'signal_llm': {
			const similar = !source.names && source.score !== null && source.score !== undefined;
			const text = similar
				? m.candidate_llm_similar({ score: percent(source.score ?? 0) })
				: m.candidate_llm();
			return [{ ...chip(text), quote: source.quote ?? null }];
		}
		case 'signal_classifier':
			return [chip(m.candidate_classifier({ score: percent(source.score ?? 0) }))];
		case 'signal_neighbours':
			return [
				{
					...chip(m.candidate_neighbours({ votes: source.votes ?? 0, found: source.found ?? 0 })),
					documents: source.documents ?? []
				}
			];
		case 'signal_facts':
			return [
				...(source.identifiers ?? []).map((kind) =>
					chip(m.candidate_identifier({ kind: identifierLabel(kind) }), true)
				),
				...(source.named_in_text ? [chip(m.candidate_named(), true)] : [])
			];
	}
}

/**
 * The candidates behind a checked value: the one it took for a contact or type, those of
 * the tags set; none if the check has no candidates (other fields, older checks).
 */
export function chosen(check: Check): Candidate[] {
	const value = check.value;
	const candidates = check.candidates ?? [];
	if (Array.isArray(value)) return candidates.filter((item) => value.includes(item.value));
	return value === null || value === undefined
		? []
		: candidates.filter((item) => item.value === value);
}

export function documentHref(id: string): string {
	return `${BASE}/documents/${id}`;
}
