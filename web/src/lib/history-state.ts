/**
 * What a page opens over itself (the Beam, a dialog) lives in its history entry
 * (`page.state`), so that the back button closes it, a reload brings it back (`persistState`)
 * and the way back from a jump returns to it open (web/DESIGN.md, "No plain data in
 * addresses"). Opening pushes an entry, a change replaces it, closing goes back to the entry
 * before it, or, where this page did not push it (a reload restored it), replaces it.
 */
import { goto } from '$app/navigation';
import { page } from '$app/state';

type Key = 'beam' | 'identifier' | 'holders';

// The keys whose entry this page pushed (else: a reload restored it).
const pushed: Partial<Record<Key, boolean>> = {};

/** Open `key` with `value` in a new history entry, beside what the entry holds. */
export function pushEntry<K extends Key>(key: K, value: App.PageState[K]): void {
	pushed[key] = true;
	void goto(page.url.href, {
		shallow: true,
		state: { ...page.state, [key]: value },
		persistState: true
	});
}

/** Change `key` in the same history entry. */
export function replaceEntry<K extends Key>(key: K, value: App.PageState[K]): void {
	void goto(page.url.href, {
		shallow: true,
		replace: true,
		state: { ...page.state, [key]: value },
		persistState: true
	});
}

/** Close `key`: back to the entry before it, or that entry's state without it. */
export function dropEntry(key: Key): void {
	if (page.state[key] === undefined) return;
	if (pushed[key]) {
		pushed[key] = false;
		history.back();
		return;
	}
	const state = { ...page.state };
	delete state[key];
	void goto(page.url.href, { shallow: true, replace: true, state, persistState: true });
}

/**
 * `key` of the history entry as one object while what it holds stays the same. Each change of
 * the entry (the Beam opening over a dialog, the back button closing it) restores every key as a
 * new object; read through this, what shows `key` does not load again, and a close by the back
 * button is noted:
 * `const wanted = $derived(identifier())` with `const identifier = entryOf('identifier')`.
 */
export function entryOf<K extends Key>(key: K): () => App.PageState[K] | undefined {
	let kept: App.PageState[K] | undefined;
	let written: string | undefined;
	return () => {
		const value = page.state[key];
		// Gone from the entry: the back button left the one this page pushed.
		if (value === undefined) pushed[key] = false;
		const now = value === undefined ? undefined : JSON.stringify(value);
		if (now !== written) {
			kept = value;
			written = now;
		}
		return kept;
	};
}
