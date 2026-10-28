/** The open identifiers (`/identifiers/open`, admins): those learned at a contact, those that
 * stand in confirmed documents at no contact, and IBANs and creditor IDs suggested for a contact
 * or a person's profile; confirming or rejecting them. */
import { api } from '#lib/api/client.ts';
import { unwrap } from '#lib/api/call.ts';
import type { components } from '#lib/api/schema.ts';
import { BASE } from '#lib/base.ts';
import { ReasonError } from '#lib/errors.ts';
import { factFilter } from '#lib/facts.ts';

export type OpenIdentifier = components['schemas']['OpenIdentifierOut'];
export type OpenPage = components['schemas']['OpenPageOut'];
export type OpenCounts = components['schemas']['OpenCountsOut'];
export type OpenDetail = components['schemas']['OpenDetailOut'];
export type OpenDecision = components['schemas']['OpenDecisionIn'];
export type OpenOutcome = components['schemas']['OutcomeOut'];
export type OpenSource = OpenIdentifier['source'];
export type OpenAction = OpenDecision['action'];

/** The key that tells an open identifier apart (its kind and normalised value). */
export function openKey(item: Pick<OpenIdentifier, 'kind' | 'value'>): string {
	return `${item.kind}:${item.value}`;
}

/** The documents that show it, in the documents list (a fact of its kind and value). */
export function documentsHref(item: Pick<OpenIdentifier, 'kind' | 'value'>): string {
	return `${BASE}/documents?fact=${encodeURIComponent(factFilter(item.kind, item.value, null))}`;
}

/** Whether "Übernehmen" knows where: a learned one's contact, the one its documents name, or
 * the contact or person a suggestion names. */
export function confirmable(item: Pick<OpenIdentifier, 'contacts' | 'person'>): boolean {
	return Boolean(item.person) || item.contacts.length === 1;
}

/** Who it belongs to, as the list names it: the person of a suggestion, else its contact. */
export function targetName(item: Pick<OpenIdentifier, 'contacts' | 'person'>): string {
	return item.person?.name ?? item.contacts[0]?.name ?? '';
}

/** All open ones, under every source. */
export function openTotal(counts: OpenCounts): number {
	return counts.learned + counts.unknown + counts.suggested;
}

export async function decide(decisions: OpenDecision[]): Promise<OpenOutcome[]> {
	return unwrap(api.POST('/api/v1/identifiers/open/decisions', { body: { decisions } }));
}

/** One decision; a ReasonError if it was not done. */
export async function decideOne(decision: OpenDecision): Promise<void> {
	const [outcome] = await decide([decision]);
	if (outcome && !outcome.done && outcome.reason) throw new ReasonError(outcome.reason);
}

export async function openCounts(): Promise<OpenCounts> {
	return unwrap(api.GET('/api/v1/identifiers/open/summary'));
}
