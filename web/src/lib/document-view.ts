/**
 * The document view: its tabs, what the model said about each field (and where its quote
 * stands on the page), and the place of a document among those waiting in the inbox.
 */
import type { components } from '#lib/api/schema.ts';
import { BASE } from '#lib/base.ts';
import { sameValue, type ApiValue } from '#lib/fields.ts';

export type Check = components['schemas']['FieldCheckOut'];
export type Review = components['schemas']['ReviewOut'];
export type Place = components['schemas']['LocationOut'];
export type Box = components['schemas']['BoxOut'];

export const TABS = ['details', 'content', 'log'] as const;
export type Tab = (typeof TABS)[number];

/** What the tabs read of a URL (SvelteKit's `page.url` is a read-only one). */
type Address = { pathname: string; search: string; searchParams: Pick<URLSearchParams, 'get'> };

/** The tab a URL names (`?tab=`); the details without one. */
export function tabOf(url: Address): Tab {
	const tab = url.searchParams.get('tab') ?? '';
	return (TABS as readonly string[]).includes(tab) ? (tab as Tab) : 'details';
}

/** The URL of `tab`, keeping the other parameters (`from=inbox`). */
export function tabHref(url: Address, tab: Tab): string {
	const params = new URLSearchParams(url.search);
	if (tab === 'details') params.delete('tab');
	else params.set('tab', tab);
	const query = params.toString();
	return query ? `${url.pathname}?${query}` : url.pathname;
}

export interface FieldEvidence {
	check: Check;
	/** The field waits for a decision. */
	open: boolean;
}

/**
 * The latest check of every field: the open ones (still to decide), else those of the latest
 * classification and field extraction. Keys as the API names fields (`contact`,
 * `field:<id>`).
 */
export function fieldEvidence(review: Review | null): Map<string, FieldEvidence> {
	const found = new Map<string, FieldEvidence>();
	if (!review) return found;
	for (const node of review.nodes) {
		for (const check of node.fields) found.set(check.field, { check, open: false });
	}
	for (const node of review.open) {
		for (const check of node.fields) found.set(check.field, { check, open: true });
	}
	return found;
}

/**
 * What backs a field: a quote that shows the value, a quote it follows from (a customer
 * number for the contact), or nothing in the text.
 */
export type Provenance = 'quote' | 'derived' | 'none';

export function provenance(check: Check): Provenance {
	if (!check.evidence?.trim()) return 'none';
	return check.quote_shows_value === false ? 'derived' : 'quote';
}

/**
 * Whether the places of a check still belong to the field: not once the value differs from
 * what was checked or suggested (someone changed it).
 */
export function placesApply(check: Check, current: ApiValue | string[] | null): boolean {
	const checked = (check.value ?? check.suggestion ?? null) as ApiValue | string[] | null;
	if (checked === null) return true;
	if (Array.isArray(checked) && Array.isArray(current)) {
		return JSON.stringify([...checked].sort()) === JSON.stringify([...current].sort());
	}
	return sameValue(checked as ApiValue, current as ApiValue | null);
}

/** A highlighted passage on a page of the viewer. */
export interface Mark {
	/** The field it belongs to. */
	key: string;
	label: string;
	page: number;
	boxes: Box[];
	/** The quote only leads to the value: drawn dashed. */
	derived: boolean;
	/** Jumped to: drawn stronger for a moment. */
	pinned: boolean;
}

export function marksOf(
	key: string,
	label: string,
	check: Check,
	{ pinned = false }: { pinned?: boolean } = {}
): Mark[] {
	const derived = provenance(check) === 'derived';
	return (check.locations ?? []).map((place) => ({
		key,
		label,
		page: place.page,
		boxes: place.boxes,
		derived,
		pinned
	}));
}

export interface Neighbours {
	/** From 1; null if the document is not (or no longer) in the list. */
	position: number | null;
	total: number;
	previous: string | null;
	next: string | null;
}

/**
 * The documents before and after `id` among `ids`, in the order of the inbox; none for a
 * document that is not among them (it left the inbox, or the list is another one).
 */
export function neighbours(ids: readonly string[], id: string): Neighbours {
	const index = ids.indexOf(id);
	if (index < 0) return { position: null, total: ids.length, previous: null, next: null };
	return {
		position: index + 1,
		total: ids.length,
		previous: ids[index - 1] ?? null,
		next: ids[index + 1] ?? null
	};
}

/** A document opened from the inbox (of every user, for an admin who chose that). */
export function inboxDocument(id: string, allUsers = false): string {
	return `${BASE}/documents/${id}?from=inbox${allUsers ? '&all=1' : ''}`;
}
