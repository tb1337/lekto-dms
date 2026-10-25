import { untrack } from 'svelte';

/**
 * Run `run` whenever `read()` changes after the first reading, without tracking what `run`
 * reads: for a reload when an admin switches the reach, for example. Call it while a component
 * is set up, like `$effect`.
 */
export function onChange<T>(read: () => T, run: (value: T, before: T) => void): void {
	let before = untrack(read);
	$effect(() => {
		const value = read();
		if (value === before) return;
		const previous = before;
		before = value;
		untrack(() => run(value, previous));
	});
}
