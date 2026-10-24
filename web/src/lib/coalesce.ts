/**
 * Events come in bursts (a run sends two for each of its nodes, some of them side by side):
 * `coalesced(run)` runs `run` once, `wait` ms after the last of a burst of calls, instead of
 * once for each.
 */
export function coalesced(run: () => void, wait = 300): { (): void; cancel(): void } {
	let timer: ReturnType<typeof setTimeout> | undefined;
	const call = () => {
		clearTimeout(timer);
		timer = setTimeout(run, wait);
	};
	call.cancel = () => clearTimeout(timer);
	return call;
}
