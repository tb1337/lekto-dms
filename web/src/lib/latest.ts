/**
 * Which of several overlapping calls is the newest: an answer that arrives after a later call
 * started is dropped, so the state shows the newest request, not the slowest.
 *
 *     const begin = latest();
 *     async function load() {
 *         const current = begin();
 *         const found = await fetchSomething();
 *         if (!current()) return; // overtaken
 *         items = found;
 *     }
 */
export function latest(): () => () => boolean {
	let count = 0;
	return () => {
		const mine = ++count;
		return () => mine === count;
	};
}
