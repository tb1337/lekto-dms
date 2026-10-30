/**
 * Where "back" leads from a document (web/DESIGN.md, "Navigation between list and detail"): the
 * document list as it was left, with its lens, filters, sort and layout, which live in its URL,
 * and its words, which live in the history entry (`lib/words.ts`). Kept in memory for this tab;
 * after a reload the way back is the bare list.
 */
import { BASE } from '#lib/base.ts';
import { gotoSearching } from '#lib/words.ts';

let documents = $state<string | null>(null);
let words = $state('');

export const returnTo = {
	/** The document list as it was left, or the bare list. */
	get documents(): string {
		return documents ?? `${BASE}/documents`;
	},
	/** The history entry of the way back: the words the list searched for. */
	get state(): App.PageState {
		return { words };
	},
	/** The list remembers its URL and words whenever they change. */
	rememberDocuments(url: { pathname: string; search: string }, searched: string): void {
		documents = url.pathname + url.search;
		words = searched;
	},
	/** Back to the list as it was left. */
	goDocuments(): Promise<void> {
		return gotoSearching(documents ?? `${BASE}/documents`, words);
	}
};
