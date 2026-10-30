/**
 * A stand-in for SvelteKit's `page` from `$app/state` that pages react to, for tests that move
 * from one address to another: `vi.mock('$app/state', async () => ({ page: (await
 * import('#lib/testing/page-state.svelte.ts')).testPage }))`, then `goTo(…)`.
 */
export const testPage = $state<{
	url: URL;
	params: Record<string, string>;
	state: App.PageState;
}>({
	// Replaced as a whole, never changed in place (as SvelteKit's).
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	url: new URL('http://lekto/ui/inbox'),
	params: {},
	state: {}
});

// The states of the history entries a test went through, the current one last.
let entries: App.PageState[] = [{}];

/** Go to `href` (below `http://lekto`) with these route parameters and this history entry. */
export function goTo(
	href: string,
	params: Record<string, string> = {},
	state: App.PageState = {}
): void {
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	testPage.url = new URL(href, 'http://lekto');
	testPage.params = params;
	testPage.state = state;
	entries = [state];
}

/** A stand-in for `goto` of `$app/navigation` that keeps the states of the history entries:
 * `vi.mock('$app/navigation', async () => ({ goto: (await import(…)).fakeGoto }))`, with
 * `history.back` spied on by `fakeBack`. */
export async function fakeGoto(
	url: string | URL,
	options: { state?: App.PageState; replace?: boolean } = {}
): Promise<void> {
	if (options.replace) entries.pop();
	entries.push(options.state ?? {});
	// eslint-disable-next-line svelte/prefer-svelte-reactivity
	testPage.url = new URL(String(url), testPage.url);
	testPage.state = options.state ?? {};
}

/** A stand-in for `history.back`: the entry before. */
export function fakeBack(): void {
	if (entries.length > 1) entries.pop();
	testPage.state = entries.at(-1) ?? {};
}
