/**
 * What the pages of one rule share (the view, the editor, the apply page, a version): the
 * rule's data is loaded beside the master data (`loadRuleLookup`, with the webhooks), which is kept while the page
 * moves to another rule, and an answer that arrives after a later load started is dropped
 * (another rule in the URL meanwhile, or a reload after a master data dialog saved).
 */
import { untrack } from 'svelte';
import { describeError } from '#lib/errors.ts';
import { latest } from '#lib/latest.ts';
import { loadRuleLookup, type Lookup } from '#lib/masterdata.svelte.ts';

export class RuleLoader {
	/** The master data; null until the first load succeeded. */
	lookup = $state<Lookup | null>(null);
	/** Why the last load failed, as text; null after a load that worked. */
	problem = $state<string | null>(null);
	#begin = latest();

	/**
	 * Load `data` beside the master data and hand both to `then`, unless a later load overtook
	 * this one; a failure sets `problem`. The master data of the load before is kept unless
	 * `fresh` asks for it anew (a master data dialog saved: the names shown may have changed).
	 */
	async load<T>(
		data: () => Promise<T>,
		then: (found: T, lookup: Lookup) => void,
		options: { fresh?: boolean } = {}
	): Promise<void> {
		const current = this.#begin();
		const kept = options.fresh ? null : untrack(() => this.lookup);
		try {
			const [found, loaded] = await Promise.all([data(), kept ?? loadRuleLookup()]);
			if (!current()) return;
			this.lookup = loaded;
			this.problem = null;
			then(found, loaded);
		} catch (error) {
			if (current()) this.problem = describeError(error);
		}
	}
}
