/**
 * How a search searched, for the hint by its hits (Tobi, 24.10.2026): by words alone and why,
 * whether the meaning of the query is still being made and when it is ready
 * (`search.meaning_ready`), and whether the answer takes long. A search that went by words
 * while its meaning is still being made stays by words for the same query (more pages, a
 * refresh after events) until the person asks for the meaning: the list does not change under
 * their hands.
 */
import type { Reason } from '#lib/reasons.ts';

/** After this long without an answer, the hint says that the meaning takes long. */
export const SLOW_AFTER = 1500;
/** After this long without `search.meaning_ready`, the hint stops promising it. */
export const PENDING_FOR = 90_000;

export interface SearchAnswer {
	mode: 'hybrid' | 'words';
	reason?: Reason | null;
	meaning_pending: boolean;
}

export interface Shown {
	query: string;
	reason: Reason;
	pending: boolean;
	ready: boolean;
}

export class SearchNote {
	shown = $state<Shown | null>(null);
	slow = $state(false);
	#pinned: string | null = null;
	#slowTimer: ReturnType<typeof setTimeout> | undefined;
	#pendingTimer: ReturnType<typeof setTimeout> | undefined;

	/** The hint for `query`, if it is about it. */
	about(query: string): Shown | null {
		return this.shown?.query === query ? this.shown : null;
	}

	/** `semantic_ratio` of a search for `query`: 0 while it stays by words. */
	ratio(query: string): number | undefined {
		return this.#pinned === query ? 0 : undefined;
	}

	/** The answer to the first page of a search for `query`. */
	answered(query: string, answer: SearchAnswer): void {
		if (this.#pinned === query) return; // by words as asked: the hint stays as it was
		clearTimeout(this.#pendingTimer);
		// Without embeddings there is no meaning to speak of.
		if (
			answer.mode !== 'words' ||
			!answer.reason ||
			answer.reason.code === 'search_no_embeddings'
		) {
			this.shown = null;
			return;
		}
		this.shown = { query, reason: answer.reason, pending: answer.meaning_pending, ready: false };
		if (!answer.meaning_pending) return;
		this.#pinned = query;
		this.#pendingTimer = setTimeout(() => {
			if (this.shown?.query === query && this.shown.pending) {
				this.shown = { ...this.shown, pending: false };
			}
		}, PENDING_FOR);
	}

	/** The meaning of `query` is ready (`search.meaning_ready`). */
	meaningReady(query: string): void {
		if (this.shown?.query !== query || !this.shown.pending) return;
		clearTimeout(this.#pendingTimer);
		this.shown = { ...this.shown, pending: false, ready: true };
	}

	/** Search with the meaning again: the next search for the query asks for it. */
	withMeaning(): void {
		clearTimeout(this.#pendingTimer);
		this.#pinned = null;
		this.shown = null;
	}

	/** Whether a search is waiting for its first page. */
	waiting(loading: boolean): void {
		clearTimeout(this.#slowTimer);
		if (!loading) {
			this.slow = false;
			return;
		}
		this.#slowTimer = setTimeout(() => (this.slow = true), SLOW_AFTER);
	}
}
