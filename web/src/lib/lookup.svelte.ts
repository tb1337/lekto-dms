/**
 * The master data a page shows names from (`loadLookup`): loaded when the page opens and anew
 * when asked (an admin switched the reach, a master data dialog saved). The newest answer wins;
 * an older one arriving late is dropped.
 */
import { describeError } from '#lib/errors.ts';
import { latest } from '#lib/latest.ts';
import { loadLookup, type Lookup } from '#lib/masterdata.svelte.ts';

export class PageLookup {
	/** The master data; null until the first load succeeded. */
	value = $state<Lookup | null>(null);
	/** Why the last load failed, as text; null after a load that worked. */
	problem = $state<string | null>(null);
	#begin = latest();
	#onerror: ((error: unknown) => void) | undefined;

	/** `onerror` hears of a failed load (for a toast); a page may show `problem` instead. */
	constructor(onerror?: (error: unknown) => void) {
		this.#onerror = onerror;
	}

	async load(): Promise<void> {
		const current = this.#begin();
		try {
			const loaded = await loadLookup();
			if (!current()) return;
			this.value = loaded;
			this.problem = null;
		} catch (error) {
			if (!current()) return;
			this.problem = describeError(error);
			this.#onerror?.(error);
		}
	}
}
