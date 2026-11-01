/**
 * A selection a link hands over (Tobi, 01.11.2026, umsetzungsplan "MCP", decision 9): an
 * assistant links to the documents it means, `/ui/documents?ids=…`, by their short ids (the
 * last characters of the id) or whole ones, comma-separated or repeated. The list shows exactly
 * them until the chip is removed; the remembered filters stay as they are (DESIGN.md, "Selection
 * by link").
 */

export const MAX_SELECTED = 100;

const ID = /^(?:[0-9a-f]{8,12}|[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12})$/;

/** The ids the link names, each once, in lower case; what is no id is left out, and so is
 * what goes beyond `MAX_SELECTED`. */
export function selectionOf(params: URLSearchParams): string[] {
	const ids = params
		.getAll('ids')
		.flatMap((value) => value.split(','))
		.map((value) => value.trim().toLowerCase())
		.filter((value) => ID.test(value));
	return [...new Set(ids)].slice(0, MAX_SELECTED);
}
