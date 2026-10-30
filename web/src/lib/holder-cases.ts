/**
 * The cases behind a number of the holders' evaluation (web/DESIGN.md, "Beam"): which measure
 * (a kind with a holder, or the recommendation) and which column, what the dialog says of them.
 */
import type { components } from '#lib/api/schema.ts';
import { labelOfKind, type IdentifierKind } from '#lib/identifiers.ts';
import { m } from '#lib/paraglide/messages.js';

export type HolderOutcome = components['schemas']['HolderOutcome'];

export interface HolderCases {
	measure: IdentifierKind | 'recommendation';
	outcome: HolderOutcome;
}

/** The columns whose numbers open their cases ("Stimmt" stays a number). */
export const CASE_OUTCOMES: readonly HolderOutcome[] = [
	'learned_rejected',
	'refused_confirmed',
	'unclear',
	'unread'
];

/** Where the measure was wrong: its cases' decisions in red. */
export function wrong(outcome: HolderOutcome): boolean {
	return outcome === 'learned_rejected' || outcome === 'refused_confirmed';
}

const COLUMNS: Record<HolderOutcome, () => string> = {
	right: m.holders_right,
	learned_rejected: m.holders_learned_rejected,
	refused_confirmed: m.holders_refused_confirmed,
	unclear: m.holders_unclear,
	unread: m.holders_unread
};

export function measureLabel(measure: HolderCases['measure']): string {
	return measure === 'recommendation' ? m.holders_recommendation() : labelOfKind(measure);
}

export function outcomeLabel(outcome: HolderOutcome): string {
	return COLUMNS[outcome]();
}

/** What the cases of `cases` are: the rule's or the recommendation's against the decision. */
export function casesText({ measure, outcome }: HolderCases): string {
	if (measure === 'recommendation') {
		if (outcome === 'learned_rejected') return m.holders_cases_recommended_learned_rejected();
		if (outcome === 'refused_confirmed') return m.holders_cases_recommended_refused_confirmed();
		return m.holders_cases_recommended_unclear();
	}
	if (outcome === 'learned_rejected') return m.holders_cases_learned_rejected();
	if (outcome === 'refused_confirmed') return m.holders_cases_refused_confirmed();
	if (outcome === 'unread') return m.holders_cases_unread();
	return m.holders_cases_unclear();
}
