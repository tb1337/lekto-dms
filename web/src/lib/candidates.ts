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
	/** What the value means where it is no probability (the language model's). */
	note: string | null;
	/** Similar documents that carry the value. */
	documents: string[];
}

const percent = (value: number) =>
	formatNumber(value, { style: 'percent', maximumFractionDigits: 0 });
const similarity = (value: number) =>
	formatNumber(value, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const given = (value: number | null | undefined): value is number =>
	value !== null && value !== undefined;

function identifierLabel(kind: string): string {
	return (IDENTIFIER_KINDS as readonly string[]).includes(kind)
		? kindLabel(kind as IdentifierKind)
		: kind;
}

/**
 * The chips of one signal's say: one, or for the facts one per identifier and the name. Each
 * tells the measured value and, where the signal names a value from a threshold on, the
 * threshold: the classifier's probability, how well the name the language model read matches
 * (the model gives no probability of its own), the votes and the highest similarity of the
 * similar documents. Older checks without them keep the shorter text.
 */
export function sourceChips(source: CandidateSource): SourceChip[] {
	const chip = (text: string, strong = source.names): SourceChip => ({
		text,
		strong,
		quote: null,
		note: null,
		documents: []
	});
	const { score, threshold } = source;
	switch (source.signal) {
		case 'signal_llm': {
			if (!given(score)) return [{ ...chip(m.candidate_llm()), quote: source.quote ?? null }];
			const text = given(threshold)
				? m.candidate_llm_match({ score: percent(score), threshold: percent(threshold) })
				: m.candidate_llm_similar({ score: percent(score) });
			return [{ ...chip(text), quote: source.quote ?? null, note: m.candidate_llm_note() }];
		}
		case 'signal_classifier':
			return [
				chip(
					given(threshold)
						? m.candidate_classifier_threshold({
								score: percent(score ?? 0),
								threshold: percent(threshold)
							})
						: m.candidate_classifier({ score: percent(score ?? 0) })
				)
			];
		case 'signal_neighbours': {
			const counted = { votes: source.votes ?? 0, found: source.found ?? 0 };
			const text = given(source.similarity)
				? m.candidate_neighbours_similar({
						...counted,
						similarity: similarity(source.similarity)
					})
				: m.candidate_neighbours(counted);
			return [{ ...chip(text), documents: source.documents ?? [] }];
		}
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

/**
 * Whether to mark a candidate as contradicted: a signal names it, and another signal named
 * another value against it. A candidate no signal names (a classifier's 29 %) is only listed:
 * nothing it says stands against anything.
 */
export function disputed(candidate: Candidate): boolean {
	return candidate.contradicted && (candidate.sources ?? []).some((source) => source.names);
}

export function documentHref(id: string): string {
	return `${BASE}/documents/${id}`;
}
