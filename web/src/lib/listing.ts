/**
 * How the document view sorts and shows its documents. The sort stands in the URL (`sort`);
 * without it, the one this browser last chose for a list or for a search, else the default:
 * a search by relevance, a list by document date, newest first. Grid or list is remembered
 * too. Remembering is a convenience: without storage the defaults hold.
 */

export type ListSort =
	'-document_date' | 'document_date' | '-created_at' | 'created_at' | 'title' | '-title';
export type Sort = ListSort | 'relevance';
export type View = 'grid' | 'list';

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
	view: 'lekto.documents.view'
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

export function rememberedView(): View {
	return stored(KEYS.view) === 'list' ? 'list' : 'grid';
}

export function rememberView(view: View): void {
	store(KEYS.view, view);
}
