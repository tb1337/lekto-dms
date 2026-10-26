/**
 * How the document view sorts and shows its documents. The sort stands in the URL (`sort`);
 * without it, the one this browser last chose for a list or for a search, else the default:
 * a search by relevance, a list by document date, newest first. Grid or list is remembered
 * too. Remembering is a convenience: without storage the defaults hold. A list (not a search)
 * sorts by the value of a field with `field` or `-field` and the field in `sort_field`, as a
 * lens may; that is not remembered.
 */

import { isoDayLocal } from '#lib/dates.ts';
import type { FieldDefinition } from '#lib/masterdata.svelte.ts';
import { m } from '#lib/paraglide/messages.js';

export type FieldSort = 'field' | '-field';
export type ListSort =
	| '-document_date'
	| 'document_date'
	| '-created_at'
	| 'created_at'
	| 'title'
	| '-title'
	| FieldSort;
export type Sort = ListSort | 'relevance';
export type Layout = 'grid' | 'list' | 'stream';

export const LAYOUTS: readonly Layout[] = ['grid', 'list', 'stream'];

export const FIELD_SORTS: readonly FieldSort[] = ['field', '-field'];
export const LIST_SORTS: readonly ListSort[] = [
	'-document_date',
	'document_date',
	'-created_at',
	'created_at',
	'title',
	'-title'
];
export const SEARCH_SORTS: readonly Sort[] = ['relevance', ...LIST_SORTS];
const DEFAULT: Record<'list' | 'search', Sort> = { list: '-document_date', search: 'relevance' };

const KEYS = {
	list: 'lekto.documents.sort.list',
	search: 'lekto.documents.sort.search',
	layout: 'lekto.documents.layout'
};

function stored(key: string): string | null {
	try {
		return globalThis.localStorage?.getItem(key) ?? null;
	} catch {
		return null;
	}
}

function store(key: string, value: string): void {
	try {
		globalThis.localStorage?.setItem(key, value);
	} catch {
		// Not remembered: the defaults hold next time.
	}
}

function valid(value: string | null, searching: boolean): Sort | null {
	const sorts: readonly string[] = searching ? SEARCH_SORTS : LIST_SORTS;
	return value !== null && sorts.includes(value) ? (value as Sort) : null;
}

const SORT_LABELS: Record<Exclude<Sort, FieldSort>, () => string> = {
	relevance: m.sort_relevance,
	'-document_date': m.sort_document_date_desc,
	document_date: m.sort_document_date_asc,
	'-created_at': m.sort_created_desc,
	created_at: m.sort_created_asc,
	title: m.sort_title_asc,
	'-title': m.sort_title_desc
};

/** How a sort reads in a menu; a sort by `field` with its name and direction. */
export function sortLabel(sort: Sort, field?: Pick<FieldDefinition, 'name' | 'data_type'>): string {
	if (!isFieldSort(sort)) return SORT_LABELS[sort]();
	const numeric = field?.data_type === 'number' || field?.data_type === 'amount';
	const label =
		sort === 'field'
			? numeric
				? m.sort_field_asc_number
				: m.sort_field_asc_date
			: numeric
				? m.sort_field_desc_number
				: m.sort_field_desc_date;
	return label({ field: field?.name ?? '' });
}

/** What a sort orders by, in a word (a field by its name), and whether it goes up or down
 * (none for relevance): the face of a compact sort menu. */
export function sortShort(
	sort: Sort,
	field?: Pick<FieldDefinition, 'name'>
): { key: string; direction: 'up' | 'down' | null } {
	if (sort === 'relevance') return { key: m.sort_short_relevance(), direction: null };
	const direction = sort.startsWith('-') ? 'down' : 'up';
	const key = sort.replace(/^-/, '');
	const names: Record<string, () => string> = {
		document_date: m.sort_short_document_date,
		created_at: m.sort_short_created,
		title: m.sort_short_title
	};
	return { key: key === 'field' ? (field?.name ?? '') : names[key](), direction };
}

export function isFieldSort(sort: Sort): sort is FieldSort {
	return (FIELD_SORTS as readonly string[]).includes(sort);
}

/** The field a list sorts by (`sort_field`), while its sort is by a field. */
export function sortFieldOf(params: URLSearchParams, searching: boolean): string | null {
	return isFieldSort(sortOf(params, searching)) ? params.get('sort_field') : null;
}

/** The sort of the view: from the URL, else remembered, else the default. */
export function sortOf(params: URLSearchParams, searching: boolean): Sort {
	const mode = searching ? 'search' : 'list';
	const asked = params.get('sort') ?? '';
	if (!searching && params.get('sort_field') && isFieldSort(asked as Sort)) {
		return asked as FieldSort;
	}
	return (
		valid(params.get('sort'), searching) ?? valid(stored(KEYS[mode]), searching) ?? DEFAULT[mode]
	);
}

/** Remember `sort` for the next list or search; the URL carries it now. */
export function rememberSort(sort: Sort, searching: boolean): void {
	if (!isFieldSort(sort)) store(KEYS[searching ? 'search' : 'list'], sort);
}

/**
 * The month a sort by date groups a document under, as `2026-10`: by its document date, or
 * by when it was added; '' for one without a document date (they come last). Null where the
 * sort does not group (relevance, title).
 */
export function monthOf(
	sort: Sort,
	document: { document_date?: string | null; created_at: string }
): string | null {
	if (sort === '-document_date' || sort === 'document_date') {
		return document.document_date?.slice(0, 7) ?? '';
	}
	if (sort === '-created_at' || sort === 'created_at') {
		// In the browser's time, as the date shows.
		return isoDayLocal(new Date(document.created_at)).slice(0, 7);
	}
	return null;
}

export interface MonthGroup<T> {
	/** `2026-10`, '' without a document date, null where the sort does not group. */
	month: string | null;
	/** Where the group starts in the list. */
	start: number;
	items: T[];
}

/**
 * The items in their order, a group for each run of one month; one group without a month
 * where the sort does not group.
 */
export function byMonth<T>(
	items: readonly T[],
	sort: Sort,
	documentOf: (item: T) => { document_date?: string | null; created_at: string }
): MonthGroup<T>[] {
	const groups: MonthGroup<T>[] = [];
	items.forEach((item, index) => {
		const month = monthOf(sort, documentOf(item));
		const last = groups.at(-1);
		if (last && last.month === month) last.items.push(item);
		else groups.push({ month, start: index, items: [item] });
	});
	return groups;
}

export function rememberedLayout(): Layout {
	const found = stored(KEYS.layout);
	return LAYOUTS.find((layout) => layout === found) ?? 'grid';
}

export function rememberLayout(layout: Layout): void {
	store(KEYS.layout, layout);
}
