/**
 * Whether the window is as wide as a desktop: from Tailwind's `lg` (64rem) on, where the
 * document view fills the window and the processing tab shows the steps and the chosen one side
 * by side. Below it the steps are a list that opens one step at a time. Tests choose with
 * `override`.
 */
import { MediaQuery } from 'svelte/reactivity';

export const DESKTOP_QUERY = '(width >= 64rem)';

class Desktop {
	#query: MediaQuery | null = null;
	#override = $state<boolean | null>(null);

	get current(): boolean {
		if (this.#override !== null) return this.#override;
		this.#query ??= new MediaQuery(DESKTOP_QUERY);
		return this.#query.current;
	}

	/** For tests: a desktop (true), a narrower screen (false), or the window again (null). */
	override(value: boolean | null): void {
		this.#override = value;
	}
}

export const desktop = new Desktop();
