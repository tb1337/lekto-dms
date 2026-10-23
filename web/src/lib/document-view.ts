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

export const TABS = ['document', 'properties', 'processing'] as const;
export type Tab = (typeof TABS)[number];

/** What the tabs read of a URL (SvelteKit's `page.url` is a read-only one). */
type Address = { pathname: string; search: string; searchParams: Pick<URLSearchParams, 'get'> };

/** The tabs of before 0.6 by the names they have now. */
const RENAMED: Record<string, Tab> = { metadata: 'properties', log: 'processing' };

/** The tab a URL names (`?tab=`); the document without one, and for the links of before
 * (`?tab=details`, `?tab=content`). */
export function tabOf(url: Address): Tab {
	const tab = url.searchParams.get('tab') ?? '';
	if (Object.hasOwn(RENAMED, tab)) return RENAMED[tab];
	return (TABS as readonly string[]).includes(tab) ? (tab as Tab) : 'document';
}

/** The URL of `tab`, keeping the other parameters (`from=inbox`, the view); the step of the
 * processing tab (`?step=`) only stays there. */
export function tabHref(url: Address, tab: Tab): string {
	const params = new URLSearchParams(url.search);
	if (tab === 'document') params.delete('tab');
	else params.set('tab', tab);
	if (tab !== 'processing') params.delete('step');
	return hrefOf(url, params);
}

/** The step of the processing tab a URL names (`?step=`); null for none, or one not in `nodes`. */
export function stepOf(url: Address, nodes: readonly string[]): string | null {
	const step = url.searchParams.get('step');
	return step !== null && nodes.includes(step) ? step : null;
}

/** The URL of the processing tab showing `step` (none: the list of steps), keeping the other
 * parameters. */
export function stepHref(url: Address, step: string | null): string {
	const params = new URLSearchParams(url.search);
	params.set('tab', 'processing');
	if (step === null) params.delete('step');
	else params.set('step', step);
	return hrefOf(url, params);
}

function hrefOf(url: Address, params: URLSearchParams): string {
	const query = params.toString();
	return query ? `${url.pathname}?${query}` : url.pathname;
}

/**
 * The document tab (Tobi, 20.10.2026): two panes, each with its switch. On the left the pages
 * or the recognised text, on the right the details (the form) or the facts. Checking takes the
 * pages and the details (once the "details" tab), reading the text and the facts (once
 * "content"); anything in between goes.
 */
export const LEFT = ['pages', 'text'] as const;
export const RIGHT = ['form', 'facts'] as const;
export type Left = (typeof LEFT)[number];
export type Right = (typeof RIGHT)[number];
export interface View {
	left: Left;
	right: Right;
}

const CHECKING: View = { left: 'pages', right: 'form' };
const READING: View = { left: 'text', right: 'facts' };

/** The view a URL names (`?left=`, `?right=`); what it does not name comes from a link of
 * before (`?tab=content` reads), else it checks: no view is remembered (Tobi, 21.10.2026). */
export function viewOf(url: Address): View {
	const tab = url.searchParams.get('tab');
	const base = tab === 'content' ? READING : CHECKING;
	const left = url.searchParams.get('left') ?? '';
	const right = url.searchParams.get('right') ?? '';
	return {
		left: (LEFT as readonly string[]).includes(left) ? (left as Left) : base.left,
		right: (RIGHT as readonly string[]).includes(right) ? (right as Right) : base.right
	};
}

/** The URL of the document tab showing `view`, keeping the other parameters but the step of the
 * processing tab. */
export function viewHref(url: Address, view: View): string {
	const params = new URLSearchParams(url.search);
	params.delete('tab');
	params.delete('step');
	params.set('left', view.left);
	params.set('right', view.right);
	return hrefOf(url, params);
}

/** The page a URL asks the document tab to show (`?page=`, from a page image of the processing
 * view); null for none. */
export function pageOf(url: Address): number | null {
	const page = Number(url.searchParams.get('page') ?? '');
	return Number.isInteger(page) && page >= 1 ? page : null;
}

/** The URL of the document tab showing the pages at page `number` (null: the link forgets the
 * page it asked for), the other pane as it is. */
export function pageHref(url: Address, number: number | null): string {
	const params = new URLSearchParams(url.search);
	params.delete('tab');
	params.delete('step');
	params.set('left', 'pages');
	params.set('right', viewOf(url).right);
	if (number === null) params.delete('page');
	else params.set('page', String(number));
	return hrefOf(url, params);
}

type Viewed = Pick<components['schemas']['DocumentDetails'], 'id' | 'media_type' | 'page_count'>;

/**
 * What the PDF viewer shows of a document: the archive PDF once it exists; before, while no
 * page images stand in, the original if it is a PDF, else nothing (an image is shown once its
 * page image exists). Nothing is asked for that cannot be there yet.
 */
export function viewerSources(document: Viewed, archive: boolean): string[] {
	const base = `/api/v1/documents/${document.id}`;
	if (archive) return [`${base}/archive`];
	return document.media_type === 'application/pdf' ? [`${base}/original`] : [];
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

/** A document of the inbox as the document view knows it: where it stands there. */
export interface InboxPlace {
	id: string;
	tab: components['schemas']['InboxTab'];
}

/**
 * The inbox anew, with `id` kept where it stood before: the open document may leave the inbox
 * while it is shown (seen when it opened, confirmed), and the way to the documents before and
 * after it stays.
 */
export function keepPlace(
	before: readonly InboxPlace[],
	now: readonly InboxPlace[],
	id: string
): InboxPlace[] {
	const kept = before.findIndex((place) => place.id === id);
	if (kept < 0 || now.some((place) => place.id === id)) return [...now];
	// After the nearest document before it that is still there; first if none is.
	let at = 0;
	for (let index = kept - 1; index >= 0 && at === 0; index--) {
		at = now.findIndex((place) => place.id === before[index].id) + 1;
	}
	return [...now.slice(0, at), before[kept], ...now.slice(at)];
}

/**
 * The document to open after confirming `id`: the next one in the inbox that waits for a
 * decision (yellow or red), else the first such before it; never one in processing or a new
 * one. Null if none is left: back to the inbox.
 */
export function nextDecision(places: readonly InboxPlace[], id: string): string | null {
	const index = places.findIndex((place) => place.id === id);
	const order = index < 0 ? places : [...places.slice(index + 1), ...places.slice(0, index)];
	return (
		order.find((place) => place.id !== id && (place.tab === 'review' || place.tab === 'intervene'))
			?.id ?? null
	);
}

/** A document opened from the inbox: its neighbours are the inbox's. */
export function inboxDocument(id: string): string {
	return `${BASE}/documents/${id}?from=inbox`;
}

/** The places of a quote by page: one per page, with the boxes of every place on it, in
 * page order (a name printed three times on page 9 is one chip). */
export function byPage(places: readonly Place[]): Place[] {
	const pages = new Map<number, Place>();
	for (const place of places) {
		const found = pages.get(place.page);
		if (found) found.boxes = [...found.boxes, ...place.boxes];
		else pages.set(place.page, { page: place.page, boxes: [...place.boxes] });
	}
	return [...pages.values()].sort((a, b) => a.page - b.page);
}
