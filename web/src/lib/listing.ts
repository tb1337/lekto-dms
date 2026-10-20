/**
 * How the document view sorts and shows its documents. The sort stands in the URL (`sort`);
 * without it, the one this browser last chose for a list or for a search, else the default:
 * a search by relevance, a list by document date, newest first. Grid or list is remembered
 * too. Remembering is a convenience: without storage the defaults hold.
 */

export type ListSort =
	'-document_date' | 'document_date' | '-created_at' | 'created_at' | 'title' | '-title';
export type Sort = ListSort | 'relevance';
export type Layout = 'grid' | 'list';

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

/** The sort of the view: from the URL, else remembered, else the default. */
export function sortOf(params: URLSearchParams, searching: boolean): Sort {
	const mode = searching ? 'search' : 'list';
	return (
		valid(params.get('sort'), searching) ?? valid(stored(KEYS[mode]), searching) ?? DEFAULT[mode]
	);
}

/** Remember `sort` for the next list or search; the URL carries it now. */
export function rememberSort(sort: Sort, searching: boolean): void {
	store(KEYS[searching ? 'search' : 'list'], sort);
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
		const added = new Date(document.created_at);
		return `${added.getFullYear()}-${String(added.getMonth() + 1).padStart(2, '0')}`;
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
	return stored(KEYS.layout) === 'list' ? 'list' : 'grid';
}

export function rememberLayout(layout: Layout): void {
	store(KEYS.layout, layout);
}
