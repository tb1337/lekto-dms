/**
 * How many rows a table shows per page (`Pagination`), chosen from a few sizes and remembered
 * per table in this browser (Tobi, 27.10.2026): wherever that table shows, the same choice
 * holds. Remembering is a convenience: without storage the default holds.
 */

/** The tables that offer a choice of page size. */
export type PagedTable = 'jobs';

/** The sizes a table offers: the jobs at most 100, as the API gives no more. */
export const PAGE_SIZES: Record<PagedTable, readonly number[]> = { jobs: [25, 50, 100] };

/** The size of a table until one is chosen: the jobs 25 (Tobi, 27.10.2026). */
export const DEFAULT_PAGE_SIZES: Record<PagedTable, number> = { jobs: 25 };

function key(table: PagedTable): string {
	return `lekto.page-size.${table}`;
}

/** The size this browser last chose for `table`, else the default. */
export function rememberedPageSize(table: PagedTable): number {
	let found: string | null = null;
	try {
		found = globalThis.localStorage?.getItem(key(table)) ?? null;
	} catch {
		// Not readable: the default holds.
	}
	const size = Number(found);
	return PAGE_SIZES[table].includes(size) ? size : DEFAULT_PAGE_SIZES[table];
}

/** Remember `size` for `table`; the default is forgotten rather than stored. */
export function rememberPageSize(table: PagedTable, size: number): void {
	try {
		if (size === DEFAULT_PAGE_SIZES[table]) globalThis.localStorage?.removeItem(key(table));
		else globalThis.localStorage?.setItem(key(table), String(size));
	} catch {
		// Not remembered: the default holds next time.
	}
}
