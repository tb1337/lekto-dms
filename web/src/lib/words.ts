/**
 * The words of the documents' search live in the history entry (`page.state.words`), never in
 * the address (web/DESIGN.md, "No plain data in addresses"): not in the browser history's
 * addresses, a bookmark or a `Referer`. `persistState` brings them back after a reload. Every
 * navigation of the documents list carries them on; a plain link (none in its state) opens the
 * list without words, or with those of the lens it names.
 */
import { goto } from '$app/navigation';

/** The words a history entry holds: a string (empty: none) if a navigation set them, else
 * undefined. */
export function stateWords(state: App.PageState): string | undefined {
	return typeof state.words === 'string' ? state.words.trim() : undefined;
}

/** Open `url` searching for `words` (empty: none). */
export function gotoSearching(
	url: string,
	words: string,
	options: { replace?: boolean; reset?: boolean } = {}
): Promise<void> {
	return goto(url, { ...options, state: { words }, persistState: true });
}
