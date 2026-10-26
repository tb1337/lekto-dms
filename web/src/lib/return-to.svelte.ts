/**
 * Where "back" leads from a document (web/DESIGN.md, "Navigation between list and detail"): the
 * document list as it was left, with its lens, filters, words, sort and layout, which all live in
 * its URL. Kept in memory for this tab; after a reload the way back is the bare list.
 */
import { BASE } from '#lib/base.ts';

let documents = $state<string | null>(null);

export const returnTo = {
	/** The document list as it was left, or the bare list. */
	get documents(): string {
		return documents ?? `${BASE}/documents`;
	},
	/** The list remembers its URL whenever it changes. */
	rememberDocuments(url: { pathname: string; search: string }): void {
		documents = url.pathname + url.search;
	}
};
